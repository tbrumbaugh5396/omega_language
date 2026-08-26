"""Finds syllable onsets in a spoken clip, so cuts can land on the voice.

The video has to cut on "four / fla / vors / one / calm". Synthesising each
syllable separately would make the timing trivial but the delivery robotic —
"fla" spoken alone is not the "fla" inside "flavors". So the phrase is spoken
once, naturally, and the cut points are recovered from the audio instead.

Onsets come from a spectral-flux-ish novelty curve rather than raw loudness:
a syllable can start on a quiet consonant, and plain RMS puts the cut late,
on the vowel. Rising energy after a dip is what the ear hears as a new
syllable, so that is what gets measured.

No numpy here — the clip is a couple of seconds of mono audio, and the
arithmetic is cheap enough in plain Python that a dependency would cost more
than it saves.
"""
import array
import pathlib
import subprocess
import wave

FFMPEG = "/usr/local/bin/ffmpeg"
HOP = 0.005                 # seconds between envelope samples
WIN = 0.020                 # analysis window


def to_wav(src, dst, rate=22050):
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(src),
                    "-ac", "1", "-ar", str(rate), str(dst)], check=True)
    return dst


def envelope(wav_path):
    """RMS per hop, plus the sample rate and total duration."""
    with wave.open(str(wav_path)) as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1
        rate = w.getframerate()
        pcm = array.array("h", w.readframes(w.getnframes()))
    hop, win = int(rate * HOP), int(rate * WIN)
    env = []
    for i in range(0, max(1, len(pcm) - win), hop):
        acc = 0
        for s in pcm[i:i + win:4]:          # every 4th sample is plenty here
            acc += s * s
        env.append((acc / max(1, len(pcm[i:i + win:4]))) ** 0.5)
    peak = max(env) or 1.0
    return [e / peak for e in env], rate, len(pcm) / rate


def smooth(xs, k=3):
    out = []
    for i in range(len(xs)):
        lo, hi = max(0, i - k), min(len(xs), i + k + 1)
        out.append(sum(xs[lo:hi]) / (hi - lo))
    return out


def onsets(env, want, min_gap=None, floor=0.08):
    """Pick `want` onsets: the strongest rises, kept apart by `min_gap`.

    The separation floor is derived from the clip rather than fixed, because
    the right value depends entirely on how fast the line is read. Too small
    and a single syllable gets picked twice — a plosive and the vowel behind
    it are two rises, and some voices separate them by barely 100ms, which
    costs a real syllable elsewhere. Too large and genuinely adjacent
    syllables get merged. Two-fifths of the average syllable spacing sits
    well clear of both failures, and moves when the delivery does.
    """
    e = smooth(env)
    novelty = [max(0.0, e[i] - e[i - 1]) for i in range(1, len(e))]
    novelty = smooth(novelty, 2)

    if min_gap is None:
        voiced = [i for i, v in enumerate(e) if v > floor]
        if not voiced:
            raise ValueError("no speech found in this clip")
        span = (voiced[-1] - voiced[0]) * HOP
        min_gap = max(0.10, 0.40 * span / want)
    gap = int(min_gap / HOP)

    order = sorted(range(len(novelty)), key=lambda i: -novelty[i])
    picked = []
    for i in order:
        if e[i + 1] < floor:                # ignore rises inside silence
            continue
        if any(abs(i - p) < gap for p in picked):
            continue
        picked.append(i)
        if len(picked) == want:
            break
    if len(picked) < want:
        # returning fewer would quietly drop cuts from the edit downstream
        raise ValueError(f"found {len(picked)} onsets, wanted {want}; "
                         f"min_gap={min_gap:.3f}s may be too large")
    picked.sort()
    # back off to where the rise actually began, so the cut is not late
    starts = []
    for i in picked:
        j = i
        while j > 0 and novelty[j - 1] > 0.002 and e[j] > floor * 0.5:
            j -= 1
        starts.append(j * HOP)
    return starts


def analyse(src, want, workdir):
    # ".mono" and not just ".wav": the source may already be a wav in this
    # same directory, and ffmpeg reading and writing one path truncates it
    wav = to_wav(src, pathlib.Path(workdir)
                 / (pathlib.Path(src).stem + ".mono.wav"))
    env, rate, dur = envelope(wav)
    return onsets(env, want), env, dur


def plot(env, marks, dur, out, w=1100, h=260):
    """Draw the envelope with the chosen cut points, to eyeball the result."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), (250, 248, 245))
    d = ImageDraw.Draw(im)
    n = len(env)
    for i, v in enumerate(env):
        x = 20 + (w - 40) * i / max(1, n - 1)
        d.line([(x, h - 30), (x, h - 30 - v * (h - 60))], fill=(150, 165, 180))
    for t in marks:
        x = 20 + (w - 40) * (t / dur)
        d.line([(x, 10), (x, h - 20)], fill=(220, 60, 60), width=2)
        d.text((x + 4, 12), f"{t:.2f}s", fill=(180, 40, 40))
    im.save(out)


def voiced_runs(env, floor=0.06, gap=0.20, min_len=0.05):
    """Stretches of speech, split wherever the clip goes quiet."""
    times = [i * HOP for i, v in enumerate(smooth(env)) if v > floor]
    if not times:
        return []
    runs, start, prev = [], times[0], times[0]
    for t in times[1:]:
        if t - prev > gap:
            runs.append((start, prev))
            start = t
        prev = t
    runs.append((start, prev))
    return [r for r in runs if r[1] - r[0] >= min_len]


def split_lines(env, syllable_counts):
    """Group voiced runs into lines, given how many syllables each line has.

    A recording of three sentences does not come apart at the three longest
    silences — a dramatic beat inside the tagline can outlast the gap between
    two sentences, and that is exactly the case here. What does separate them
    is proportion: a line with 25 syllables has to occupy about 25/36ths of
    the talking. So every way of cutting the runs into the right number of
    groups gets scored against the script's own shape, and the best fit wins.

    Comparing *voiced* time rather than elapsed time is what makes this work
    — pauses vary with delivery, but time spent actually speaking tracks
    syllable count closely.

    Returns one (start, end) per line.
    """
    runs = voiced_runs(env)
    n = len(syllable_counts)
    if len(runs) < n:
        raise ValueError(f"only {len(runs)} voiced runs for {n} lines")

    spoken = [b - a for a, b in runs]
    total = sum(spoken)
    want = [c / sum(syllable_counts) * total for c in syllable_counts]

    best, best_cost = None, float("inf")
    def walk(idx, at, groups):
        nonlocal best, best_cost
        left = n - len(groups) - 1
        if left == 0:
            groups = groups + [(at, len(runs))]
            cost = 0.0
            for (lo, hi), exp in zip(groups, want):
                got = sum(spoken[lo:hi])
                cost += ((got - exp) / exp) ** 2
            if cost < best_cost:
                best, best_cost = groups, cost
            return
        for cut in range(at + 1, len(runs) - left + 1):
            walk(cut, cut, groups + [(at, cut)])
    walk(0, 0, [])

    return [(runs[lo][0], runs[hi - 1][1]) for lo, hi in best]

// The instrument editor: a patch, and something to hear it with.
//
// Deliberately the smallest editor in the studio. An instrument is text — one
// line per node — so this is a text area, a list of what did not parse, a
// keyboard to play it on, and the library id it registers under. There is no
// node canvas and no wiring by mouse, because the patch already says the
// thing a canvas would draw and says it in fewer characters.
//
// Saving registers the instrument in the library under `you.<name>`, so a
// Canvas or a Playground document can reference it by that name and get it
// back on the next reload. That is the whole point of the document type: an
// instrument that outlives the session it was made in.

import { el, clear, toast } from "./ui.js";
import { parsePatch, toPatch, STARTER_PATCH } from "./instrument-doc.js";
import { defineInstrument, instrumentId } from "./instrument-library.js";
import { LiveInstrument } from "./live-audio.js";
import { noteHz } from "./dsp-song.js";

/** A new instrument document. */
export const newInstrumentDoc = () => ({ patch: STARTER_PATCH });

/** What a new instrument can start from. Each is a patch, and each is short
    enough to read before changing a number in it. */
export const INSTRUMENT_STARTERS = [
  { label: "Enveloped tone", patch: STARTER_PATCH },
  { label: "Filtered saw", patch: `// A saw through a resonant filter — the ordinary subtractive voice.
// @instrument saw
// @voices 4

note = voice.note
env  = env.ad      gate=note.gate  attackMs=4  decayMs=320
osc  = osc.saw     amp=0.5  blep=1
filt = filter.svf  x=osc.y  freq=1200  q=4
out  = gain.smooth x=filt.lp  level=1  ms=1
` },
  { label: "Two-oscillator hum", patch: `// A voice over a low saw whose level a document's effect can move:
// { kind: "param", node: "hum", param: "level", value: … }
// @instrument hum
// @voices 8

note  = voice.note
voice = osc.sineHz  hz=note.hz  gate=note.gate  amp=0.35
low   = osc.saw     hz=55  amp=0.18  blep=1
hum   = gain.smooth x=low.y  level=0  ms=60
out   = mix.add     a=voice.y  b=hum.y  gainA=1  gainB=1
` },
  { label: "Plucked string", patch: `// A short burst of noise into a comb: the string is the delay, and its
// length is the pitch. Not tuned by the note yet — set ms and hear it.
// @instrument pluck
// @voices 4

note  = voice.note
env   = env.ad      gate=note.gate  attackMs=0.5  decayMs=8
exc   = noise.white amp=0.8
burst = osc.sineHz  hz=note.hz  gate=env.y  amp=0.4
out   = filter.comb x=burst.y  ms=4  mix=0.9
` },
];

/** The name a document's instrument goes into the library under. */
export function instrumentNameFor(doc, projectName = "") {
  const said = parsePatch(doc && doc.patch ? doc.patch : "").meta.instrument;
  const raw = String(said || projectName || "instrument").trim();
  const slug = raw.replace(/[^A-Za-z0-9]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase() || "instrument";
  return raw.includes(".") ? raw : `you.${slug}`;
}

// The two octaves the keyboard offers, as MIDI numbers with their labels.
const KEYS = [
  [60, "C"], [62, "D"], [64, "E"], [65, "F"], [67, "G"], [69, "A"], [71, "B"], [72, "C"],
];

export function instrumentEditor(host) {
  const doc = host.data;
  doc.patch ||= STARTER_PATCH;

  const area = el("textarea", {
    spellcheck: "false",
    style: { width: "100%", minHeight: "17rem", fontFamily: "ui-monospace, monospace",
             fontSize: ".82rem", lineHeight: "1.5", tabSize: "2" },
  });
  area.value = doc.patch;

  const problems = el("div.stack", { style: { gap: ".1rem" } });
  const idLine = el("p.fine", {});
  const status = el("p.fine", {});
  let decl = null, live = null, voice = 0;

  const reparse = () => {
    const { decl: d, errors, meta } = parsePatch(area.value);
    decl = errors.length ? null : d;
    clear(problems);
    for (const e of errors.slice(0, 6)) {
      problems.append(el("p.fine", { style: { color: "var(--bad, #f2708a)", margin: 0 } }, e));
    }
    if (errors.length > 6) problems.append(el("p.fine", {}, `…and ${errors.length - 6} more`));
    if (decl) {
      const name = instrumentNameFor(doc, host.doc.name);
      // Registered as soon as it parses: an editor whose instrument only
      // exists after a save is an editor you cannot audition from a document
      // in another tab.
      defineInstrument(name, decl);
      const parts = Object.keys(decl.parts || {});
      idLine.textContent = `${name} · ${instrumentId(decl)} · `
        + `${decl.graph.nodes.length} nodes, ${decl.voices} voices · parts a document can address: ${parts.join(", ")}`;
    } else {
      idLine.textContent = meta.instrument ? `@instrument ${meta.instrument} — not registered while it does not parse` : "";
    }
    // A changed patch is a changed instrument; the old worklet is not it.
    if (live) { live.close(); live = null; }
    return decl;
  };

  const audition = async (midi) => {
    if (!reparse()) { toast("This patch does not parse yet"); return; }
    try {
      if (!live) {
        live = await LiveInstrument.create({ graph: decl.graph, noteNode: decl.noteNode,
                                             voices: decl.voices, gain: decl.gain, parts: decl.parts });
        await live.resume();
      }
      // Round-robin by hand, so holding down the row overlaps rather than
      // cutting itself off — the allocator would do it too, but this way the
      // editor is audibly polyphonic without a note list.
      voice = (voice + 1) % decl.voices;
      live.perform([{ kind: "note", hz: noteHz(midi), dur: 0.6 }]);
      status.textContent = `playing ${midi} · ${live.notes} note${live.notes === 1 ? "" : "s"} so far`;
    } catch (e) {
      status.textContent = String(e.message).split("\n")[0];
    }
  };

  const keyboard = el("div.row", { style: { flexWrap: "wrap", gap: ".25rem" } },
    ...KEYS.map(([midi, label]) => el("button", { onclick: () => audition(midi) }, label)));

  area.oninput = () => { doc.patch = area.value; reparse(); host.save(); };

  reparse();

  return el("div.stack", { style: { gap: ".6rem" } },
    el("p.fine", {}, "One line per node: ",
      el("code", {}, "name = type key=value …"),
      ". A value is a number, or ", el("code", {}, "other.port"), " to wire it. ",
      "Every name here is a part a document's effects can address."),
    area,
    problems,
    idLine,
    el("div.row", { style: { alignItems: "center", gap: ".5rem" } },
      el("span.fine", {}, "Audition"), keyboard),
    status,
    el("div.row", {},
      el("button", { onclick: () => {
        const d = reparse();
        if (!d) { toast("Nothing to tidy while it does not parse"); return; }
        const { meta } = parsePatch(area.value);
        area.value = toPatch(d, { name: meta.instrument, title: meta.title });
        doc.patch = area.value; reparse(); host.save();
      } }, "Tidy"),
      el("button", { onclick: () => {
        area.value = STARTER_PATCH; doc.patch = area.value; reparse(); host.save();
      } }, "Start over")));
}

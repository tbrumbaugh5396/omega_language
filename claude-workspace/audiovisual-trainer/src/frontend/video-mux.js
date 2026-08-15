// A minimal MP4 muxer.
//
// WebCodecs will encode H.264 and AAC, but browsers ship no muxer, so the
// encoded chunks have to be written into a container by hand. This writes a
// plain (non-fragmented) MP4: ftyp, then mdat holding every sample, then moov
// describing them. moov-at-the-end is legal and much simpler than patching
// offsets afterwards; it costs nothing for a file being downloaded rather
// than streamed.
//
// One chunk per track keeps the sample-to-chunk table trivial: all video
// samples are contiguous, then all audio samples, so each track needs exactly
// one stsc entry and one chunk offset.

const TIMESCALE = 1_000_000;          // microseconds, which is what WebCodecs speaks

const u8 = (...bytes) => new Uint8Array(bytes);

function u32(n) {
  return u8((n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255);
}
function u16(n) {
  return u8((n >> 8) & 255, n & 255);
}
function u64(n) {
  const hi = Math.floor(n / 2 ** 32);
  return concat(u32(hi), u32(n >>> 0));
}
function ascii(s) {
  return new Uint8Array([...s].map((c) => c.charCodeAt(0)));
}

function concat(...parts) {
  const flat = parts.flat(4).filter(Boolean);
  let len = 0;
  for (const p of flat) len += p.length;
  const out = new Uint8Array(len);
  let o = 0;
  for (const p of flat) { out.set(p, o); o += p.length; }
  return out;
}

function box(type, ...payload) {
  const body = concat(...payload);
  return concat(u32(body.length + 8), ascii(type), body);
}
function fullBox(type, version, flags, ...payload) {
  return box(type, u8(version), u8((flags >> 16) & 255, (flags >> 8) & 255, flags & 255), ...payload);
}

/** Run-length encode per-sample deltas into an stts table. */
function sttsEntries(deltas) {
  const entries = [];
  for (const d of deltas) {
    const last = entries[entries.length - 1];
    if (last && last.delta === d) last.count++;
    else entries.push({ count: 1, delta: d });
  }
  return entries;
}

function stblFor(track) {
  const { samples, sampleEntry, timescale } = track;
  const deltas = samples.map((s, i) =>
    i < samples.length - 1
      ? Math.max(1, Math.round(((samples[i + 1].timestamp - s.timestamp) / 1e6) * timescale))
      : Math.max(1, Math.round(((s.duration || 0) / 1e6) * timescale) || 1));
  const stts = sttsEntries(deltas);

  const parts = [
    box("stsd", concat(u32(0) /* version+flags */, u32(1), sampleEntry)),
    fullBox("stts", 0, 0, u32(stts.length),
      ...stts.map((e) => concat(u32(e.count), u32(e.delta)))),
  ];

  // stss lists sync samples. Audio is all-sync, so the box is omitted there;
  // for video an absent stss would claim every frame is a keyframe.
  if (track.kind === "video") {
    const keys = [];
    samples.forEach((s, i) => { if (s.type === "key") keys.push(i + 1); });
    if (keys.length && keys.length !== samples.length) {
      parts.push(fullBox("stss", 0, 0, u32(keys.length), ...keys.map(u32)));
    }
  }

  parts.push(
    fullBox("stsc", 0, 0, u32(1), concat(u32(1), u32(samples.length), u32(1))),
    fullBox("stsz", 0, 0, u32(0), u32(samples.length),
      ...samples.map((s) => u32(s.data.length))),
    fullBox("stco", 0, 0, u32(1), u32(track.chunkOffset)),
  );
  return box("stbl", ...parts);
}

function trakFor(track, id, durationUs) {
  const durTs = Math.round((durationUs / 1e6) * track.timescale);
  const tkhd = fullBox("tkhd", 0, 3,
    u32(0), u32(0), u32(id), u32(0),
    u32(Math.round((durationUs / 1e6) * TIMESCALE)),
    u32(0), u32(0),
    u16(0), u16(track.kind === "audio" ? 1 : 0),   // layer, alternate group
    u16(track.kind === "audio" ? 0x0100 : 0), u16(0),
    // unity matrix
    concat(u32(0x00010000), u32(0), u32(0), u32(0), u32(0x00010000), u32(0),
           u32(0), u32(0), u32(0x40000000)),
    u32(track.kind === "video" ? track.width << 16 : 0),
    u32(track.kind === "video" ? track.height << 16 : 0));

  const mdhd = fullBox("mdhd", 0, 0,
    u32(0), u32(0), u32(track.timescale), u32(durTs), u16(0x55c4), u16(0));

  const hdlr = fullBox("hdlr", 0, 0, u32(0),
    ascii(track.kind === "video" ? "vide" : "soun"),
    u32(0), u32(0), u32(0),
    ascii(track.kind === "video" ? "VideoHandler\0" : "SoundHandler\0"));

  const dinf = box("dinf", fullBox("dref", 0, 0, u32(1), fullBox("url ", 0, 1)));
  const header = track.kind === "video"
    ? fullBox("vmhd", 0, 1, u16(0), u16(0), u16(0), u16(0))
    : fullBox("smhd", 0, 0, u16(0), u16(0));

  return box("trak", tkhd,
    box("mdia", mdhd, hdlr,
      box("minf", header, dinf, stblFor(track))));
}

function avc1Entry(track) {
  const avcC = box("avcC", track.description);
  return box("avc1",
    u8(0, 0, 0, 0, 0, 0), u16(1),            // reserved, data_reference_index
    u16(0), u16(0), u32(0), u32(0), u32(0),  // pre_defined / reserved
    u16(track.width), u16(track.height),
    u32(0x00480000), u32(0x00480000),        // 72 dpi
    u32(0), u16(1),
    concat(u8(0), new Uint8Array(31)),       // compressor name, 32 bytes
    u16(0x0018), u16(0xffff),
    avcC);
}

function mp4aEntry(track) {
  // esds carries the AudioSpecificConfig the decoder needs.
  const asc = track.description || new Uint8Array([0x12, 0x10]);
  const decSpecific = concat(u8(0x05, asc.length), asc);
  const decConfig = concat(
    u8(0x04, 13 + decSpecific.length),
    u8(0x40),                      // MPEG-4 AAC
    u8(0x15),                      // audio stream
    u8(0, 0, 0),                   // buffer size
    u32(0), u32(0),                // max / avg bitrate
    decSpecific);
  const esDesc = concat(
    u8(0x03, 3 + decConfig.length + 3),
    u16(1), u8(0),
    decConfig,
    u8(0x06, 1, 0x02));
  return box("mp4a",
    u8(0, 0, 0, 0, 0, 0), u16(1),
    u32(0), u32(0),
    u16(track.channels), u16(16),
    u16(0), u16(0),
    u32(track.timescale << 16),
    fullBox("esds", 0, 0, esDesc));
}

/**
 * @param tracks [{ kind:'video'|'audio', samples:[{data,timestamp,duration,type}],
 *                  description:Uint8Array, width, height, timescale, channels }]
 * Returns a Blob of type video/mp4.
 */
export function muxMp4(tracks) {
  const live = tracks.filter((t) => t && t.samples.length);
  if (!live.length) throw new Error("nothing to mux");

  const ftyp = box("ftyp", ascii("isom"), u32(0x200),
    ascii("isom"), ascii("iso2"), ascii("avc1"), ascii("mp41"));

  // Lay the sample data out, recording where each track's chunk starts. The
  // mdat payload begins 8 bytes into the box, after ftyp.
  let offset = ftyp.length + 8;
  const payloads = [];
  for (const t of live) {
    t.chunkOffset = offset;
    for (const s of t.samples) { payloads.push(s.data); offset += s.data.length; }
  }
  const mdatBody = concat(...payloads);
  const mdat = concat(u32(mdatBody.length + 8), ascii("mdat"), mdatBody);

  const durationUs = Math.max(...live.map((t) => {
    const last = t.samples[t.samples.length - 1];
    return last.timestamp + (last.duration || 0);
  }));

  for (const t of live) {
    t.sampleEntry = t.kind === "video" ? avc1Entry(t) : mp4aEntry(t);
  }

  const mvhd = fullBox("mvhd", 0, 0,
    u32(0), u32(0), u32(TIMESCALE),
    u32(Math.round((durationUs / 1e6) * TIMESCALE)),
    u32(0x00010000), u16(0x0100), u16(0), u32(0), u32(0),
    concat(u32(0x00010000), u32(0), u32(0), u32(0), u32(0x00010000), u32(0),
           u32(0), u32(0), u32(0x40000000)),
    concat(u32(0), u32(0), u32(0), u32(0), u32(0), u32(0)),
    u32(live.length + 1));

  const moov = box("moov", mvhd,
    ...live.map((t, i) => trakFor(t, i + 1, durationUs)));

  return new Blob([ftyp, mdat, moov], { type: "video/mp4" });
}

export const MUX_TIMESCALE = TIMESCALE;

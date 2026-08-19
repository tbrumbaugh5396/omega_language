// A ZIP writer, stored rather than compressed.
//
// An image sequence is PNGs, and a PNG is already deflated — running it
// through deflate again costs time and saves nothing. So this writes the
// STORED method, which needs no compressor at all: the format is a local
// header per file, a central directory, and an end record, and the only real
// work is the CRC-32 every entry carries.
//
// Zip64 is not written. Past 4 GB, or past 65,535 files, the format needs it
// and this says so rather than producing a file that unpacks wrongly.

const TABLE = (() => {
  const t = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[i] = c >>> 0;
  }
  return t;
})();

export function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = TABLE[(c ^ bytes[i]) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** MS-DOS date and time, which is what a ZIP entry carries. */
function dosStamp(date) {
  const y = Math.max(1980, date.getFullYear());
  return {
    time: (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1),
    date: ((y - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate(),
  };
}

/**
 * `files` are `{ name, bytes }`. Returns a Blob.
 * `stamp` is a Date — passed in rather than read from the clock, so the same
 * frames produce the same archive twice over.
 */
export function zipStore(files, { stamp = new Date(1980, 0, 1) } = {}) {
  if (files.length > 65535) throw new Error("more than 65,535 files needs Zip64, which this does not write");
  const enc = new TextEncoder();
  const { time, date } = dosStamp(stamp);
  const locals = [], central = [];
  let offset = 0;

  for (const f of files) {
    const name = enc.encode(f.name);
    const data = f.bytes;
    if (offset + data.length > 0xffffffff) throw new Error("past 4 GB an archive needs Zip64, which this does not write");
    const crc = crc32(data);
    const lh = new DataView(new ArrayBuffer(30));
    lh.setUint32(0, 0x04034b50, true);
    lh.setUint16(4, 20, true);            // version needed
    lh.setUint16(6, 0, true);             // flags
    lh.setUint16(8, 0, true);             // stored
    lh.setUint16(10, time, true);
    lh.setUint16(12, date, true);
    lh.setUint32(14, crc, true);
    lh.setUint32(18, data.length, true);
    lh.setUint32(22, data.length, true);
    lh.setUint16(26, name.length, true);
    lh.setUint16(28, 0, true);
    locals.push(new Uint8Array(lh.buffer), name, data);

    const ch = new DataView(new ArrayBuffer(46));
    ch.setUint32(0, 0x02014b50, true);
    ch.setUint16(4, 20, true);            // version made by
    ch.setUint16(6, 20, true);            // version needed
    ch.setUint16(8, 0, true);
    ch.setUint16(10, 0, true);            // stored
    ch.setUint16(12, time, true);
    ch.setUint16(14, date, true);
    ch.setUint32(16, crc, true);
    ch.setUint32(20, data.length, true);
    ch.setUint32(24, data.length, true);
    ch.setUint16(28, name.length, true);
    ch.setUint32(42, offset, true);
    central.push(new Uint8Array(ch.buffer), name);

    offset += 30 + name.length + data.length;
  }

  let centralSize = 0;
  for (const part of central) centralSize += part.length;
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);

  return new Blob([...locals, ...central, new Uint8Array(end.buffer)], { type: "application/zip" });
}

/** A canvas as PNG bytes, for an archive entry. */
export async function pngBytes(canvas) {
  const blob = await new Promise((res) => canvas.toBlob(res, "image/png"));
  return new Uint8Array(await blob.arrayBuffer());
}

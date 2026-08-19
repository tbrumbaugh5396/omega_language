// .cube files: the interchange format a look travels in.
//
// A .cube is a text file of RGB triples in the order red fastest, then green,
// then blue — a cube of size N holding N³ entries. Parsing it is nearly
// trivial; what matters is the two things that get it wrong in practice, and
// both are handled here: DOMAIN_MIN/MAX (a log-space LUT does not run 0 to 1)
// and 1D LUTs, which some vendors ship and which have to be widened into a
// cube before anything can sample them.

/**
 * Parse a .cube into `{ size, data }`, where data is base64 of N³ RGB bytes
 * in the file's own order — small enough to live in a document.
 */
export function parseCube(text) {
  let size = 0, is1d = false;
  let dmin = [0, 0, 0], dmax = [1, 1, 1];
  const rows = [];
  let title = "";
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line[0] === "#") continue;
    const up = line.toUpperCase();
    if (up.startsWith("TITLE")) { title = line.slice(5).trim().replace(/^"|"$/g, ""); continue; }
    if (up.startsWith("LUT_3D_SIZE")) { size = parseInt(line.split(/\s+/)[1], 10); continue; }
    if (up.startsWith("LUT_1D_SIZE")) { size = parseInt(line.split(/\s+/)[1], 10); is1d = true; continue; }
    if (up.startsWith("DOMAIN_MIN")) { dmin = line.split(/\s+/).slice(1, 4).map(Number); continue; }
    if (up.startsWith("DOMAIN_MAX")) { dmax = line.split(/\s+/).slice(1, 4).map(Number); continue; }
    if (/^[-+.\d]/.test(line)) {
      const v = line.split(/\s+/).map(Number);
      if (v.length >= 3 && v.every(Number.isFinite)) rows.push(v);
    }
  }
  if (!size) throw new Error("no LUT_3D_SIZE or LUT_1D_SIZE in that file");
  const want = is1d ? size : size * size * size;
  if (rows.length < want) throw new Error(`the file says ${size}${is1d ? "" : "³"} but has ${rows.length} of ${want} rows`);

  const n = is1d ? Math.min(64, size) : size;
  const out = new Uint8Array(n * n * n * 3);
  const enc = (v) => Math.max(0, Math.min(255, Math.round(v * 255)));
  if (is1d) {
    // A curve applied per channel: widen it into a cube so one node samples both.
    for (let b = 0; b < n; b++) {
      for (let g = 0; g < n; g++) {
        for (let r = 0; r < n; r++) {
          const i = ((b * n + g) * n + r) * 3;
          const at = (k, ch) => {
            const x = (k / (n - 1)) * (size - 1);
            const lo = Math.floor(x), hi = Math.min(size - 1, lo + 1), f = x - lo;
            return rows[lo][ch] + (rows[hi][ch] - rows[lo][ch]) * f;
          };
          out[i] = enc(at(r, 0)); out[i + 1] = enc(at(g, 1)); out[i + 2] = enc(at(b, 2));
        }
      }
    }
  } else {
    for (let k = 0; k < want; k++) {
      const v = rows[k];
      out[k * 3] = enc(v[0]); out[k * 3 + 1] = enc(v[1]); out[k * 3 + 2] = enc(v[2]);
    }
  }
  let bin = "";
  for (let i = 0; i < out.length; i += 8192) {
    bin += String.fromCharCode.apply(null, out.subarray(i, i + 8192));
  }
  return { size: n, data: btoa(bin), title,
           domain: (dmin.some((x) => x !== 0) || dmax.some((x) => x !== 1)) ? { min: dmin, max: dmax } : null };
}

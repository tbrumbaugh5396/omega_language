// A design frame → a Generate sketch, through the shared emitter in
// sdf-core.js (the same one svg-to-sdf.js feeds).
//
// The Design studio's document is already structure — rects, ellipses, lines,
// text blocks, images, in a tree with transforms — so nothing has to be
// recovered from pixels; it only has to be translated. Every shape becomes a
// signed-distance function of q (frame pixels, y down, like SVG); fills and
// strokes become coverage; painter's order becomes a mix chain.
//
// Text goes through a glyph atlas (glyph-atlas.js): the browser rasterises
// each character, an exact distance transform turns it into a field, and the
// text becomes one texture sample per glyph. Greeked bars remain the fallback
// when no atlas can be built.

import { num, hex, I, mul, translate, rotateAbout, localise, emitSketch, fitPreview } from "./sdf-core.js";
import { buildAtlas, emitTextRun, GLYPH_HELPER } from "./glyph-atlas.js";

export { fitPreview };

/**
 * Compile one frame (and everything inside it) to a sketch.
 *
 * Asynchronous because real text needs a glyph atlas, and building one means
 * rasterising and distance-transforming every character the design uses.
 * @returns { source, width, height, shapes, images, notes }
 */
export async function compileDesignFrame(frame, opts = {}) {
  const W = Math.max(1, Math.round(frame.w)), H = Math.max(1, Math.round(frame.h));
  const items = [];
  const uniforms = [];
  const notes = [];
  const texts = [];
  let imgCount = 0;

  function visit(node, parentWorld, parentOpacity, depth) {
    if (node.visible === false) return;
    const local = mul(translate(node.x || 0, node.y || 0),
                      node.rotation ? rotateAbout(node.rotation, node.w / 2, node.h / 2) : I);
    // The frame we are compiling is the origin: its own position is ignored,
    // exactly as the SVG export does.
    const world = depth === 0
      ? (node.rotation ? rotateAbout(node.rotation, node.w / 2, node.h / 2) : I)
      : mul(parentWorld, local);
    const opacity = parentOpacity * (node.opacity ?? 1);
    const w = num(node.w), h = num(node.h);
    const blend = node.blend === "multiply" ? "multiply"
                : node.blend === "screen" ? "screen" : "normal";
    const strokeW = Number(node.strokeWidth) || 0;
    const strokeCol = node.stroke ? hex(node.stroke) : null;

    if (node.type === "frame" || node.type === "rect") {
      items.push({
        name: node.name || node.type, world, opacity, blend,
        comment: `${node.type} "${node.name || ""}" ${Math.round(node.w)}×${Math.round(node.h)}`,
        body: `  return sdRR(lq, vec2(${w}, ${h}), ${num(node.radius || 0)});`,
        fill: node.type === "frame" ? hex(node.fill, "#ffffff")
            : (node.fill && node.fill !== "none" ? hex(node.fill) : null),
        stroke: strokeCol || (strokeW > 0 ? "#202020" : null),
        strokeWidth: strokeW,
      });
    } else if (node.type === "ellipse") {
      items.push({
        name: node.name || "ellipse", world, opacity, blend,
        comment: `ellipse "${node.name || ""}"`,
        body: `  return sdEllipse(lq - vec2(${w}, ${h}) * 0.5, vec2(${w}, ${h}) * 0.5);`,
        fill: node.fill && node.fill !== "none" ? hex(node.fill) : null,
        stroke: strokeCol || (strokeW > 0 ? "#202020" : null),
        strokeWidth: strokeW,
      });
    } else if (node.type === "line") {
      items.push({
        name: node.name || "line", world, opacity, blend,
        comment: `line "${node.name || ""}"`,
        body: `  return sdSegment(lq, vec2(0.0), vec2(${w}, ${h}));`,
        stroke: strokeCol || "#000000",
        strokeWidth: strokeW || 2,
        open: true,
      });
    } else if (node.type === "text") {
      const size = Number(node.fontSize) || 32;
      const lines = String(node.text ?? "Text").split("\n");
      const item = {
        name: node.name || "text", world, opacity, blend,
        comment: `text "${lines[0].slice(0, 32).replace(/"/g, "'")}"`,
        fill: hex(node.fill, "#111111"),
        __text: {
          run: { text: String(node.text ?? "Text"), family: node.fontFamily || "system-ui, sans-serif",
                 weight: node.fontWeight || 500, style: "normal" },
          opts: { size, lineHeight: Number(node.lineHeight) || 1.3,
                  letterSpacing: Number(node.letterSpacing) || 0,
                  align: node.align || "left", boxWidth: node.w,
                  firstBaseline: size * 0.92 },
          lines,
        },
      };
      items.push(item);
      texts.push(item);
    } else if (node.type === "image" && node.href) {
      const u = `img_${++imgCount}`;
      uniforms.push(`uniform sampler2D ${u};   // @${/^data:/.test(node.href) ? "data" : "asset"} ${node.href}`,
                    `uniform vec2 ${u}_size;`);
      items.push({
        name: node.name || "image", world, opacity, blend,
        comment: `image "${node.name || ""}"`,
        body: `  return sdRR(lq, vec2(${w}, ${h}), ${num(node.radius || 0)});`,
        extra: `vec3 @ID@_pix(vec2 q) {   // the picture, covering its box like preserveAspectRatio: slice
${localise(world)}
  vec2 size = vec2(${w}, ${h});
  vec2 iu = lq / size;
  float ra = size.x / size.y, ia = ${u}_size.x / max(${u}_size.y, 1.0);
  vec2 s = ra > ia ? vec2(1.0, ia / ra) : vec2(ra / ia, 1.0);
  iu = (iu - 0.5) * s + 0.5;
  return ${u}_size.x > 0.5 ? texture2D(${u}, vec2(iu.x, 1.0 - iu.y)).rgb : vec3(0.5);
}`,
        fill: { expr: "@ID@_pix(q)" },
      });
    }

    if (node.children) for (const c of node.children) visit(c, world, opacity, depth + 1);
  }

  visit(frame, I, 1, 0);

  // One atlas for the whole frame, then each text item gets its glyph chain.
  const preFuncs = [];
  if (texts.length) {
    const atlas = opts.text === "greek" ? null : await buildAtlas(texts.map((t) => t.__text.run));
    if (atlas) {
      uniforms.push(`uniform sampler2D u_font;   // @hidden the glyph atlas @data ${atlas.dataUrl}`);
      preFuncs.push(GLYPH_HELPER);
      for (const it of texts) {
        const r = emitTextRun(atlas, it.__text.run, it.__text.opts);
        if (r) { it.body = r.body; it.comment += ` — ${r.glyphs} glyphs`; }
        else greek(it);
      }
    } else {
      for (const it of texts) greek(it);
      notes.push("no glyph atlas could be built — text is greeked as bars");
    }
    for (const it of texts) delete it.__text;
  }

  const source = emitSketch(items, {
    width: W, height: H,
    title: `Compiled from the design "${frame.name || "frame"}"`,
    background: hex(frame.fill, "#ffffff"),
    uniforms, preFuncs,
  });
  return { source, width: W, height: H, shapes: items.length, images: imgCount, notes };

  /** The old behaviour, kept as the fallback: one bar per line. */
  function greek(it) {
    const { opts: o, lines } = it.__text;
    const bars = lines.map((line, i) => {
      const wid = Math.min(o.boxWidth, Math.max(o.size * 0.4, [...line].length * o.size * 0.52));
      const x0 = o.align === "center" ? (o.boxWidth - wid) / 2
               : o.align === "right" ? o.boxWidth - wid : 0;
      const y0 = i * o.lineHeight * o.size + o.size * 0.28;
      return `  d = min(d, sdRR(lq - vec2(${num(x0)}, ${num(y0)}), vec2(${num(wid)}, ${num(o.size * 0.56)}), ${num(o.size * 0.28)}));`;
    });
    it.body = `  float d = 1e5;\n${bars.join("\n")}\n  return d;`;
  }
}

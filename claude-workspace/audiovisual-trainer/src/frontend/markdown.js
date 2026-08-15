// A small markdown renderer for the course documents.
//
// Deliberately not a general one. It handles exactly what these documents use
// — headings, lists, tables, fenced code, emphasis, links, block quotes and
// images — and it does two things a general renderer would not:
//
//   · an image whose path matches a live figure is replaced by that figure,
//     so the same markdown renders as a static file elsewhere and as an
//     interactive canvas here;
//   · LaTeX is transliterated to Unicode rather than typeset. That is an
//     honest compromise: no dependency, readable inline maths, and the block
//     equations are shown as source in a monospace rule so nobody mistakes
//     them for rendered output.

import { el } from "./ui.js";

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
const esc = (s) => s.replace(/[&<>]/g, (c) => ESC[c]);

// ------------------------------------------------------------------ maths

const GREEK = {
  alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", zeta: "ζ",
  eta: "η", theta: "θ", iota: "ι", kappa: "κ", lambda: "λ", mu: "μ", nu: "ν",
  xi: "ξ", pi: "π", rho: "ρ", sigma: "σ", tau: "τ", upsilon: "υ", phi: "φ",
  chi: "χ", psi: "ψ", omega: "ω", Gamma: "Γ", Delta: "Δ", Theta: "Θ",
  Lambda: "Λ", Xi: "Ξ", Pi: "Π", Sigma: "Σ", Phi: "Φ", Psi: "Ψ", Omega: "Ω",
};
const OPS = {
  int: "∫", iint: "∬", oint: "∮", sum: "Σ", prod: "Π", sqrt: "√",
  partial: "∂", nabla: "∇", infty: "∞", approx: "≈", neq: "≠", equiv: "≡",
  le: "≤", ge: "≥", leq: "≤", geq: "≥", times: "×", cdot: "·", pm: "±",
  to: "→", rightarrow: "→", leftarrow: "←", mapsto: "↦", in: "∈",
  subset: "⊂", cup: "∪", cap: "∩", forall: "∀", exists: "∃", propto: "∝",
  perp: "⊥", angle: "∠", circ: "∘", ldots: "…", dots: "…", quad: "  ",
  qquad: "    ", left: "", right: "", displaystyle: "", ",": " ", ";": " ",
  "!": "", " ": " ",
};
const SUP = { 0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷",
              8: "⁸", 9: "⁹", "+": "⁺", "-": "⁻", n: "ⁿ", i: "ⁱ" };
const SUB = { 0: "₀", 1: "₁", 2: "₂", 3: "₃", 4: "₄", 5: "₅", 6: "₆", 7: "₇",
              8: "₈", 9: "₉", "+": "₊", "-": "₋", a: "ₐ", e: "ₑ", i: "ᵢ",
              j: "ⱼ", n: "ₙ", x: "ₓ" };

/** Best-effort LaTeX → Unicode. Good enough to read, never claimed as typeset. */
export function mathToText(src) {
  let s = src;
  s = s.replace(/\\(?:mathbf|mathrm|mathit|text|operatorname)\{([^{}]*)\}/g, "$1");
  s = s.replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, "($1)/($2)");
  s = s.replace(/\\sqrt\{([^{}]*)\}/g, "√($1)");
  s = s.replace(/\\bar\{([^{}]*)\}/g, "$1̄");
  s = s.replace(/\\hat\{([^{}]*)\}/g, "$1̂");
  s = s.replace(/\\vec\{([^{}]*)\}/g, "$1⃗");
  s = s.replace(/\\([A-Za-z]+)/g, (m, name) => {
    if (GREEK[name] !== undefined) return GREEK[name];
    if (OPS[name] !== undefined) return OPS[name];
    return name;
  });
  s = s.replace(/\\([,;!\s])/g, " ");
  s = s.replace(/\^\{([^{}]*)\}/g, (m, g) => toScript(g, SUP));
  s = s.replace(/\^(\w)/g, (m, g) => toScript(g, SUP));
  s = s.replace(/_\{([^{}]*)\}/g, (m, g) => toScript(g, SUB));
  s = s.replace(/_(\w)/g, (m, g) => toScript(g, SUB));
  s = s.replace(/[{}]/g, "");
  return s.replace(/\s+/g, " ").trim();
}
const toScript = (g, map) =>
  [...g].every((c) => map[c]) ? [...g].map((c) => map[c]).join("") : `^(${g})`;

// ------------------------------------------------------------------ inline

function inline(text) {
  let s = esc(text);
  // Inline maths first, so its underscores are not read as emphasis.
  s = s.replace(/\$([^$]+)\$/g, (m, g) => `<span class="mth">${esc(mathToText(g))}</span>`);
  s = s.replace(/`([^`]+)`/g, (m, g) => `<code>${g}</code>`);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, href) =>
    /^https?:/.test(href)
      ? `<a href="${href}" target="_blank" rel="noopener">${label}</a>`
      : `<a href="#" data-doc="${href.replace(/\.md$/, "")}">${label}</a>`);
  return s;
}

// ------------------------------------------------------------------ blocks

/**
 * @param md      the document text
 * @param onFigure (path, alt) -> Node|null. Return a node to replace the
 *                 image with, or null to fall back to an <img>.
 * @param onLink   (slug) -> void, for cross-document links.
 */
export function renderMarkdown(md, { onFigure, onLink } = {}) {
  const root = el("div.md");
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  const html = (tag, s) => {
    const n = el(tag);
    n.innerHTML = s;
    return n;
  };

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i++; continue; }

    // fenced code
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++;
      root.append(el("pre.md-code", { "data-lang": lang },
        el("code", {}, buf.join("\n"))));
      continue;
    }

    // display maths
    if (line.trim() === "$$") {
      const buf = [];
      i++;
      while (i < lines.length && lines[i].trim() !== "$$") buf.push(lines[i++]);
      i++;
      root.append(el("div.md-math", {}, mathToText(buf.join(" "))));
      continue;
    }

    // heading
    const hm = /^(#{1,6})\s+(.*)$/.exec(line);
    if (hm) {
      const level = Math.min(6, hm[1].length + 1);   // h1 in the doc is a page title
      const node = html(`h${level}`, inline(hm[2]));
      node.id = "sec-" + hm[2].toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
      root.append(node);
      i++;
      continue;
    }

    // horizontal rule
    if (/^(-{3,}|\*{3,})\s*$/.test(line)) { root.append(el("hr")); i++; continue; }

    // table
    if (line.trim().startsWith("|") && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || "")) {
      const head = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(splitRow(lines[i++]));
      const table = el("table");
      table.append(el("thead", {}, el("tr", {}, ...head.map((c) => html("th", inline(c))))));
      table.append(el("tbody", {}, ...rows.map((r) =>
        el("tr", {}, ...r.map((c) => html("td", inline(c)))))));
      root.append(el("div.wrap-scroll", {}, table));
      continue;
    }

    // block quote
    if (line.startsWith(">")) {
      const buf = [];
      while (i < lines.length && lines[i].startsWith(">")) buf.push(lines[i++].replace(/^>\s?/, ""));
      root.append(html("blockquote", inline(buf.join(" "))));
      continue;
    }

    // lists, including nested one level
    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const list = el(ordered ? "ol.bullets" : "ul.bullets");
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        const indent = /^\s*/.exec(lines[i])[0].length;
        let text = lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, "");
        i++;
        // continuation lines
        while (i < lines.length && lines[i].trim() &&
               !/^\s*([-*+]|\d+\.)\s+/.test(lines[i]) &&
               !/^#{1,6}\s/.test(lines[i]) && !lines[i].startsWith("```")) {
          text += " " + lines[i++].trim();
        }
        const item = html("li", inline(text));
        if (indent >= 2 && list.lastChild) {
          let sub = list.lastChild.querySelector("ul");
          if (!sub) { sub = el("ul.bullets"); list.lastChild.append(sub); }
          sub.append(item);
        } else list.append(item);
      }
      root.append(list);
      continue;
    }

    // standalone image → live figure if we have one
    const im = /^!\[([^\]]*)\]\(([^)\s]+)\)\s*$/.exec(line.trim());
    if (im) {
      const [, alt, path] = im;
      const replacement = onFigure?.(path, alt);
      if (replacement) root.append(replacement);
      else {
        const name = path.split("/").pop();
        root.append(el("figure.course-figure", {},
          el("img", { src: `/api/course/figure/${name}`, alt,
                      style: { maxWidth: "100%", borderRadius: "8px" } }),
          el("figcaption", {}, alt)));
      }
      i++;
      continue;
    }

    // paragraph
    const buf = [];
    while (i < lines.length && lines[i].trim() &&
           !/^(#{1,6}\s|\s*([-*+]|\d+\.)\s|>|```|\|)/.test(lines[i]) &&
           lines[i].trim() !== "$$" &&
           !/^!\[[^\]]*\]\([^)\s]+\)\s*$/.test(lines[i].trim())) {
      buf.push(lines[i++]);
    }
    if (buf.length) root.append(html("p", inline(buf.join(" "))));
    else i++;
  }

  if (onLink) {
    root.querySelectorAll("a[data-doc]").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        onLink(a.getAttribute("data-doc").split("/").pop());
      });
    });
  }
  return root;
}

const splitRow = (line) =>
  line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

// The studio shell: project browser, document lifecycle, shared asset store.
//
// Five editors that have almost nothing in common internally, but share a
// document row, an asset store, an AI panel, and a link back to the week's
// piece — so this file owns all of that and hands each editor a small context.

import { el, clear, api, toast, confirmDialog, modal, closeModal, relTime } from "./ui.js";
import { aiChip } from "./ai.js";
import { userNodes, userNodeProblems, ensureUserNodes } from "./node-library.js";
import { canvasEditor } from "./studio-canvas.js";
import { musicEditor } from "./studio-music.js";
import { videoEditor } from "./studio-video.js";
import { shaderEditor, SHADER_PRESETS } from "./studio-shader.js";
import { designEditor, newDesignDoc, FRAME_PRESETS } from "./studio-design.js";
import { generateEditor, newGenerateDoc, GENERATE_PRESETS } from "./studio-generate.js";
import { instrumentEditor, INSTRUMENT_STARTERS, instrumentNameFor } from "./studio-instrument.js";
import { ensureUserInstruments, listInstruments } from "./instrument-library.js";
import { toPatch } from "./instrument-doc.js";
import { LiveInstrument } from "./live-audio.js";
import { noteHz } from "./dsp-song.js";
import { parsePatch } from "./instrument-doc.js";
import "./field-nodes.js";
import "./sim-nodes.js";
import "./game-nodes.js";

const EDITORS = { canvas: canvasEditor, music: musicEditor, video: videoEditor,
                  shader: shaderEditor, design: designEditor, instrument: instrumentEditor,
                  generate: generateEditor };

const KINDS = [
  { id: "canvas", title: "Canvas", blurb:
    "Layers, brushes, shapes and type, with the whole effects catalogue as a " +
    "filter menu. Start blank or import an image." },
  { id: "music", title: "Music", blurb:
    "Tracks, a piano roll and a step sequencer over synths built from the " +
    "same primitives the drills use. Import audio as a sampler track." },
  { id: "video", title: "Video", blurb:
    "A timeline for clips, stills and audio, with per-clip grading, " +
    "transitions and titles. Exports a recording of the composed timeline." },
  { id: "design", title: "Design", blurb:
    "Vector shapes, type and layout on an infinite canvas. Frames, snapping, "
    + "auto-layout, alignment and a column grid. Exports SVG and PNG." },
  { id: "shader", title: "Shader", blurb:
    "A GLSL sketchpad with The Book of Shaders' uniform names, so examples " +
    "from the book paste in and run unchanged. Chapter presets included." },
  { id: "instrument", title: "Instrument", blurb:
    "A patch — one line per DSP node — that any document can name and play. " +
    "Saved here, it is in the library on the next reload." },
  { id: "generate", title: "Generate", blurb:
    "One colour expression, and every uniform you declare becomes a slider, " +
    "swatch or pad. Randomise, then export a PNG at print size." },
];

export async function studioView(ctx) {
  // Deep link: #studio/<kind>/<id> opens an editor directly.
  if (ctx.sub && ctx.arg) return openEditor(ctx, ctx.sub, +ctx.arg);
  if (ctx.sub && /^\d+$/.test(ctx.sub)) return openEditor(ctx, null, +ctx.sub);

  const root = el("div");
  const { projects } = await api("/api/studio/projects");

  root.append(el("div.card", {},
    el("div.spread", {},
      el("h2", {}, "Studio"),
      aiChip()),
    el("p.dim", {}, "Where the pieces actually get made. Everything here is a " +
      "document on this machine; nothing is uploaded anywhere unless you " +
      "switch on a cloud model and send it a prompt yourself."),
    el("div.g3.grid", { style: { marginTop: ".8rem" } },
      ...KINDS.map((k) => el("div.card.tight", {},
        el("b", {}, k.title),
        el("p.fine", {}, k.blurb),
        el("button.primary", { style: { marginTop: ".4rem" },
          onclick: () => newProject(ctx, k.id) }, `New ${k.title.toLowerCase()}`))))));

  if (!projects.length) {
    root.append(el("div.card.empty", {}, "No documents yet. Start one above — " +
      "or accept a brief on the Make tab first, so the thing you build has a " +
      "constraint to push against."));
    return root;
  }

  root.append(el("div.card", {},
    el("h2", {}, "Documents", el("span.fine", {}, `${projects.length}`)),
    el("div.candidates", {}, ...projects.map((p) => projectTile(ctx, p)))));
  // The library may still be arriving; the card fills itself in when it does.
  const nodeCard = el("div", {});
  root.append(nodeCard);
  ensureUserNodes().then(() => { clear(nodeCard); nodeCard.append(nodeLibraryCard(ctx)); });
  const instCard = el("div", {}, instrumentLibraryCard(ctx));
  root.append(instCard);
  // The instrument documents, likewise: an instrument is in the library once
  // its document has been read, and a document that references one by name
  // finds it from then on.
  ensureUserInstruments({ api, parsePatch, nameFor: instrumentNameFor })
    .then(() => { clear(instCard); instCard.append(instrumentLibraryCard(ctx)); });
  return root;
}

/**
 * The nodes you have written: Generate documents with `@node` in the header,
 * which is the whole of what makes one. They are listed here because a node
 * is used somewhere other than where it is edited, and a library you cannot
 * see is one you forget you have.
 */
function nodeLibraryCard(ctx) {
  const mine = userNodes(), broken = userNodeProblems();
  if (!mine.length && !broken.length) {
    return el("div.card", {},
      el("h2", {}, "Your nodes"),
      el("p.fine", {}, "None yet. Any Generate sketch becomes an effect in Canvas and Video the moment " +
        "it says `// @node <name>` in its header — the Save as node button in Generate writes that line " +
        "for you. A stack of effects can also be frozen into one, from the Canvas layer panel."));
  }
  const row = (n) => el("div.spread", { style: { alignItems: "baseline", gap: ".5rem" } },
    el("div", {},
      el("button.ghost", { style: { padding: ".1em .3em" },
        onclick: () => n.docId && ctx.go("studio", "generate", String(n.docId)) }, n.name),
      el("span.fine", {}, ` ${n.id}`)),
    el("span.fine", {}, n.error ? "" : `${n.inputs.length} input${n.inputs.length === 1 ? "" : "s"} · `
      + `${n.params.filter((u) => u.control !== "image").length} controls`
      + (n.module ? ` · ${n.module}` : "")));
  return el("div.card", {},
    el("h2", {}, "Your nodes", el("span.fine", {}, `${mine.length}`)),
    el("p.fine", {}, "Each of these is a Generate document — editing the sketch changes the node " +
      "everywhere it is used. They appear in the effect menus in Canvas and Video."),
    el("div.stack", { style: { gap: ".25rem" } }, ...mine.map(row)),
    ...broken.map((n) => el("p.fine", { style: { color: "var(--bad, #e06c5a)" } },
      `${n.name || n.id}: ${n.error}`)));
}

/**
 * What the library has. Every instrument once, with the names it answers to,
 * what it is made of, an audition, and the patch — because an instrument you
 * cannot read or hear is one you will not use.
 */
function instrumentLibraryCard(ctx) {
  const rows = listInstruments();
  if (!rows.length) {
    return el("div.card", {}, el("h2", {}, "Instruments"),
      el("p.fine", {}, "None. The built-ins register at load, so this being empty is a bug."));
  }
  let live = null, current = null;
  const play = async (row, midi) => {
    try {
      if (current !== row.decl) {
        if (live) await live.close();
        live = await LiveInstrument.create({ graph: row.decl.graph, noteNode: row.decl.noteNode,
                                             voices: row.decl.voices, gain: row.decl.gain,
                                             parts: row.decl.parts || {} });
        await live.resume();
        current = row.decl;
      }
      live.perform([{ kind: "note", hz: noteHz(midi), dur: 0.5 }]);
    } catch (e) { toast(String(e.message).split("\n")[0]); }
  };
  const line = (row) => {
    const named = row.names.length > 0;
    const ref = named ? row.names[0] : row.id;
    const patch = el("pre.fine", { hidden: true,
      style: { margin: ".3rem 0 0", padding: ".5rem", background: "rgba(255,255,255,.04)",
               borderRadius: "6px", overflowX: "auto", whiteSpace: "pre" } });
    return el("div", { style: { padding: ".35rem 0", borderTop: "1px solid rgba(255,255,255,.06)" } },
      el("div.spread", { style: { alignItems: "baseline", gap: ".5rem", flexWrap: "wrap" } },
        el("div", {},
          el("strong", {}, ref),
          el("span.fine", {}, row.names.length > 1 ? `  also ${row.names.slice(1).join(", ")}` : ""),
          // An instrument with no name is known only by what it sounds like,
          // and printing that twice says nothing the first one did not.
          el("span.fine", {}, named ? `  ${row.id}` : "")),
        el("div.row", { style: { gap: ".2rem" } },
          ...[60, 64, 67].map((m) => el("button.ghost", { style: { padding: ".1em .45em" },
            onclick: () => play(row, m) }, "♪")),
          el("button.ghost", { style: { padding: ".1em .45em" }, onclick: () => {
            if (patch.hidden) patch.textContent = toPatch(row.decl, { name: named ? ref : null });
            patch.hidden = !patch.hidden;
          } }, "patch"))),
      el("p.fine", { style: { margin: 0 } },
        `${row.builtIn ? "built in" : named ? "yours" : "interned by a document this session"}`
        + ` · ${row.nodes} nodes · ${row.voices} voices`
        + (row.gain !== 1 ? ` · gain ${row.gain}` : "")
        + ` · ${row.types.join(", ")}`
        + (row.parts.length ? ` · parts: ${row.parts.join(", ")}` : "")),
      patch);
  };
  // "Yours" is the ones a document of yours named. The nameless ones were
  // interned by some document while it ran and are here for the session only.
  const yours = rows.filter((r) => !r.builtIn && r.names.length).length;
  const anon = rows.filter((r) => !r.names.length).length;
  return el("div.card", {},
    el("h2", {}, "Instruments", el("span.fine", {}, `${rows.length}`)),
    el("p.fine", {}, "A document plays these by name — ",
      el("code", {}, `{ ref: "tone.bell" }`),
      " — or by what it sounds like, which is the ", el("code", {}, "inst."), " id and does not move when "
      + "somebody renames it. Every part listed is a name an effect can address. "
      + (yours ? `${yours} came from your own instrument documents. `
               : "Make an Instrument document and it appears here on the next reload. ")
      + (anon ? `${anon} more were interned by a document while it ran, and are here for this session only.` : "")),
    el("div.stack", { style: { gap: 0 } }, ...rows.map(line)));
}

function projectTile(ctx, p) {
  const open = () => ctx.go("studio", p.kind, String(p.id));
  return el("div.candidate", { style: { cursor: "pointer" } },
    p.thumb
      ? el("img", { src: p.thumb, alt: "", onclick: open,
                    style: { width: "100%", display: "block", borderRadius: "6px" } })
      : el("div", { onclick: open, style: {
          height: "96px", display: "grid", placeItems: "center",
          background: "var(--bg)", borderRadius: "6px", color: "var(--ink-3)",
        } }, p.kind),
    el("div.spread", { style: { marginTop: ".4rem" } },
      el("div", { onclick: open },
        el("b", {}, p.name),
        el("div.row.tight", {},
          el("span.tag", {}, p.kind),
          el("span.fine", {}, relTime(p.updated)))),
      el("button.ghost.danger", {
        onclick: async (e) => {
          e.stopPropagation();
          if (await confirmDialog(`Delete "${p.name}"?`,
              "The document and any media imported into it go too.")) {
            await api(`/api/studio/projects/${p.id}`, { method: "DELETE" });
            ctx.go("studio");
          }
        },
      }, "×")));
}

async function newProject(ctx, kind) {
  const name = el("input", { value: "", placeholder: "name it" });
  let pieces = [];
  try { pieces = (await api("/api/pieces")).pieces.filter((p) => p.status !== "shipped"); }
  catch { /* pieces are optional here */ }
  const piece = el("select", {},
    el("option", { value: "" }, "— not tied to a piece —"),
    ...pieces.map((p) => el("option", { value: p.id },
      `${p.week} · ${p.title || p.brief?.form || "untitled"}`)));

  const preset = el("select", {}, ...presetsFor(kind).map((p, i) =>
    el("option", { value: i, selected: i === 0 }, p.label)));

  modal(
    el("h2", {}, `New ${kind}`),
    el("label", {}, "Name", name),
    el("label", {}, "Preset", preset),
    pieces.length ? el("label", {}, "For which piece?", piece) : null,
    el("div.row", { style: { justifyContent: "flex-end", marginTop: ".6rem" } },
      el("button", { onclick: closeModal }, "Cancel"),
      el("button.primary", {
        onclick: async () => {
          const p = presetsFor(kind)[+preset.value];
          const { id } = await api("/api/studio/projects", {
            method: "POST",
            body: {
              name: name.value.trim() || p.label,
              kind,
              data: p.data(),
              piece_id: piece.value ? +piece.value : null,
            },
          });
          closeModal();
          ctx.go("studio", kind, String(id));
        },
      }, "Create")));
}

function presetsFor(kind) {
  if (kind === "canvas") {
    return [
      { label: "Square 1080", data: () => blankCanvas(1080, 1080) },
      { label: "Poster 1080×1350", data: () => blankCanvas(1080, 1350) },
      { label: "Wide 1920×1080", data: () => blankCanvas(1920, 1080) },
      { label: "Story 1080×1920", data: () => blankCanvas(1080, 1920) },
    ];
  }
  if (kind === "music") {
    return [
      { label: "4 bars at 120", data: () => blankMusic(120, 4) },
      { label: "8 bars at 96", data: () => blankMusic(96, 8) },
      { label: "8 bars at 140 (half-time)", data: () => blankMusic(140, 8) },
      { label: "4 bars at 174", data: () => blankMusic(174, 4) },
    ];
  }
  if (kind === "design") {
    return FRAME_PRESETS.map(([name, w, h]) => ({
      label: `${name} — ${w}×${h}`,
      data: () => newDesignDoc(name),
    }));
  }
  if (kind === "generate") {
    return GENERATE_PRESETS.map((p) => ({
      label: p.label,
      data: () => newGenerateDoc(p),
    }));
  }
  if (kind === "instrument") {
    return INSTRUMENT_STARTERS.map((st) => ({ label: st.label, data: () => ({ patch: st.patch }) }));
  }
  if (kind === "shader") {
    return SHADER_PRESETS.map((p) => ({
      label: p.label,
      data: () => ({ source: p.source, preset: p.id, knobs: [0.5, 0.5, 0.5, 0.5] }),
    }));
  }
  return [
    { label: "1920×1080 at 30fps", data: () => blankVideo(1920, 1080, 30) },
    { label: "1080×1080 at 30fps", data: () => blankVideo(1080, 1080, 30) },
    { label: "1080×1920 at 30fps", data: () => blankVideo(1080, 1920, 30) },
  ];
}

const blankCanvas = (w, h) => ({
  width: w, height: h, background: "#ffffff",
  layers: [{ id: 1, name: "Layer 1", visible: true, opacity: 1,
             blend: "source-over", data: "" }],
});

const blankMusic = (bpm, bars) => ({
  bpm, bars, swing: 0,
  tracks: [
    { id: 1, name: "Drums", instrument: "drums", vol: 0.9, pan: 0, mute: false,
      notes: [], fx: defaultFx() },
    { id: 2, name: "Bass", instrument: "bass", vol: 0.8, pan: 0, mute: false,
      notes: [], fx: defaultFx() },
    { id: 3, name: "Keys", instrument: "synth", vol: 0.7, pan: 0, mute: false,
      notes: [], fx: defaultFx() },
  ],
});

const defaultFx = () => ({
  eqFreq: 800, eqGain: 0, eqQ: 1,
  drive: 0, delayMs: 0, delayFb: 0.25, reverb: 0, reverbDecay: 1.6,
});

const blankVideo = (w, h, fps) => ({
  width: w, height: h, fps, clips: [], audio: [],
});

// ------------------------------------------------------------------ editor host

async function openEditor(ctx, kind, id) {
  const doc = await api(`/api/studio/projects/${id}`);
  const editor = EDITORS[doc.kind];
  if (!editor) {
    return el("div.card", {}, el("p.err", {}, `No editor for "${doc.kind}".`));
  }

  // The context every editor gets: the document, the save path, asset upload,
  // and the way back out.
  let saveTimer = null;
  const host = {
    ctx,
    doc,
    data: doc.data,
    dirty: false,
    setName(name) { doc.name = name; host.save(); },
    save(thumb) {
      host.dirty = true;
      clearTimeout(saveTimer);
      saveTimer = setTimeout(async () => {
        try {
          await api(`/api/studio/projects/${id}`, {
            method: "PUT",
            body: { name: doc.name, kind: doc.kind, data: host.data,
                    thumb: thumb ?? doc.thumb ?? "", piece_id: doc.piece_id },
          });
          if (thumb) doc.thumb = thumb;
          host.dirty = false;
          status.textContent = "saved";
          status.style.color = "";
        } catch (e) {
          status.textContent = `not saved — ${e.message}`;
          status.style.color = "var(--bad)";
        }
      }, 700);
      status.textContent = "…";
    },
    async saveNow(thumb) {
      clearTimeout(saveTimer);
      await api(`/api/studio/projects/${id}`, {
        method: "PUT",
        body: { name: doc.name, kind: doc.kind, data: host.data,
                thumb: thumb ?? doc.thumb ?? "", piece_id: doc.piece_id },
      });
      if (thumb) doc.thumb = thumb;
      host.dirty = false;
      status.textContent = "saved";
    },
    async upload(file, meta = {}) {
      const q = new URLSearchParams({
        name: file.name, mime: file.type || "", project_id: String(id),
        meta: JSON.stringify(meta),
      });
      const res = await fetch(`/api/studio/assets?${q}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${localStorage.getItem("av-trainer-token")}` },
        body: file,
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "upload failed");
      const asset = await res.json();
      doc.assets.push(asset);
      return asset;
    },
    assets: doc.assets,
  };

  const status = el("span.fine", {}, "saved");
  const nameInput = el("input", {
    value: doc.name, style: { width: "auto", minWidth: "12ch", maxWidth: "26ch" },
    onchange: (e) => host.setName(e.target.value.trim() || "untitled"),
  });

  const root = el("div");
  const body = el("div");
  root.append(
    el("div.card.tight", {},
      el("div.spread", {},
        el("div.row.tight", {},
          el("button.ghost", { onclick: async () => {
            if (host.dirty) { try { await host.saveNow(); } catch { /* reported */ } }
            ctx.go("studio");
          } }, "‹ Studio"),
          nameInput,
          el("span.tag", {}, doc.kind),
          status),
        el("div.row.tight", {}, aiChip()))),
    body);

  clear(body);
  const editorNode = await editor(host);
  body.append(editorNode);
  // The shell tears down whatever it replaces, but the editor is nested a
  // level deeper than the node the shell sees, so carry its teardown up.
  root._cleanup = () => editorNode._cleanup?.();
  return root;
}

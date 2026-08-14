// The AI layer, used from the lab, the studio and the make track.
//
// Part 13 of the roadmap is specific about the shape of this: describe the
// goal perceptually, get an implementation, run it, say what is wrong
// perceptually, ask why the fix worked. And Part 13.5 is specific about the
// limit — the model is for coverage, never for judgement, and never the
// selector. The UI reflects both: it will draft, implement and list things
// you may have missed, and there is deliberately no "which of these is best"
// button anywhere in it.

import { el, api, toast, modal, closeModal } from "./ui.js";

let cached = null;

export async function aiConfig(force = false) {
  if (!cached || force) cached = await api("/api/ai/config");
  return cached;
}

export async function aiReady() {
  try {
    const c = await aiConfig();
    return c.provider && c.provider !== "off";
  } catch {
    return false;
  }
}

export async function ask(task, prompt, { context = "", maxTokens = null } = {}) {
  return api("/api/ai/complete", {
    method: "POST",
    body: { task, prompt, context, max_tokens: maxTokens },
  });
}

/**
 * A button that opens a prompt box, calls the model, and hands the result to
 * `onResult`. `describe` is shown above the box — it is where the caller
 * explains what the model is being asked to do, which keeps the "coverage,
 * not judgement" boundary visible at the point of use.
 */
export function aiButton(label, { task, describe, placeholder, context,
                                  onResult, primary = false }) {
  return el(primary ? "button.primary" : "button", {
    onclick: async () => {
      if (!(await aiReady())) return aiSettings();
      const box = el("textarea", {
        placeholder: placeholder || "Describe what you want, in perceptual terms.",
        style: { minHeight: "6em" },
      });
      const status = el("p.fine");
      const go = el("button.primary", {
        onclick: async () => {
          const text = box.value.trim();
          if (!text) { toast("Say what you want first"); return; }
          go.disabled = true;
          status.textContent = "Thinking…";
          try {
            const ctxStr = typeof context === "function" ? context() : (context || "");
            const res = await ask(task, text, { context: ctxStr });
            closeModal();
            onResult(res);
          } catch (e) {
            status.textContent = e.message;
            status.style.color = "var(--bad)";
            go.disabled = false;
          }
        },
      }, "Send");
      modal(
        el("h2", {}, label),
        describe ? el("p.dim", {}, describe) : null,
        box,
        status,
        el("div.row", { style: { justifyContent: "flex-end" } },
          el("button", { onclick: closeModal }, "Cancel"), go));
    },
  }, label);
}

/** Provider settings. Deliberately blunt about what leaves the machine. */
export async function aiSettings(onSaved) {
  const cfg = await aiConfig(true);
  const provider = el("select", {},
    ...[["off", "Off — no model, nothing leaves this machine"],
        ["anthropic", "Anthropic API (Claude)"],
        ["ollama", "Ollama — local models on this machine"],
        ["openai", "OpenAI-compatible endpoint"]].map(([v, t]) =>
      el("option", { value: v, selected: v === cfg.provider }, t)));
  const model = el("input", { value: cfg.model || "", placeholder: "claude-opus-5" });
  const baseUrl = el("input", { value: cfg.base_url || "",
    placeholder: "http://127.0.0.1:11434 or https://api.openai.com/v1" });
  const key = el("input", { type: "password", placeholder: cfg.has_key
    ? "a key is saved — type to replace it" : "paste your API key" });
  const maxTokens = el("input", { type: "number", value: cfg.max_tokens || 2000,
    min: 256, max: 8000 });
  const warn = el("p.fine");

  const syncWarning = () => {
    const p = provider.value;
    if (p === "off") {
      warn.textContent = "Nothing is sent anywhere.";
      warn.style.color = "";
    } else if (p === "ollama") {
      warn.textContent = "Ollama runs on this machine, so your prompts stay " +
        "local. Make sure `ollama serve` is running.";
      warn.style.color = "";
    } else {
      warn.textContent = "Prompts you send — including any brief, notes or " +
        "project description you attach as context — leave this machine and " +
        "go to that provider. Your API key is stored on this machine and is " +
        "never sent to the browser.";
      warn.style.color = "var(--warm)";
    }
    model.placeholder = p === "ollama" ? "llama3.1"
      : p === "openai" ? "gpt-4o-mini" : "claude-opus-5";
  };
  provider.onchange = syncWarning;
  syncWarning();

  modal(
    el("h2", {}, "AI provider"),
    el("p.dim", {}, "The model drafts, implements and lists things you might " +
      "have missed. It does not choose. Model taste regresses to the mean, " +
      "and the whole point of the drills is that yours does not."),
    el("label", {}, "Provider", provider),
    el("label", {}, "Model", model),
    el("label", {}, "Base URL (Ollama / OpenAI-compatible only)", baseUrl),
    el("label", {}, "API key", key),
    el("label", {}, "Max tokens per reply", maxTokens),
    warn,
    el("div.row", { style: { justifyContent: "flex-end", marginTop: ".6rem" } },
      el("button", { onclick: closeModal }, "Cancel"),
      el("button.primary", {
        onclick: async () => {
          try {
            await api("/api/ai/config", {
              method: "PUT",
              body: {
                provider: provider.value,
                model: model.value.trim(),
                base_url: baseUrl.value.trim(),
                max_tokens: +maxTokens.value || 2000,
                // Omitted key keeps the stored one; typing replaces it.
                ...(key.value ? { api_key: key.value } : {}),
              },
            });
            await aiConfig(true);
            closeModal();
            toast("Saved");
            onSaved?.();
          } catch (e) { toast(e.message); }
        },
      }, "Save")));
}

/** Small status chip with a link into settings; used in editor toolbars. */
export function aiChip() {
  const chip = el("button.ghost", { onclick: () => aiSettings(() => refresh()) }, "AI…");
  const refresh = async () => {
    try {
      const c = await aiConfig(true);
      chip.textContent = c.provider === "off" ? "AI: off" : `AI: ${c.model || c.provider}`;
      chip.classList.toggle("on", c.provider !== "off");
    } catch { chip.textContent = "AI…"; }
  };
  refresh();
  return chip;
}

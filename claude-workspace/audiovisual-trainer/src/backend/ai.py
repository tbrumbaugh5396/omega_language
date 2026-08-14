"""LLM / agent proxy.

Three providers, one shape. The request goes through the backend rather than
straight from the browser for two reasons: the API key never reaches the
client, and there is no CORS problem to work around.

Standard library only — urllib does everything needed here, and adding an
HTTP client dependency to move one JSON body would be silly.

On the roadmap's own terms (Part 13.5): the model is used for *coverage* —
drafts, candidates, implementations, things you might have missed — and never
as the selector. Model taste regresses to the mean; the whole app is built on
the premise that yours does not. The system prompts below say so explicitly,
because a critique prompt that does not forbid ranking will rank.
"""
import json
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db

router = APIRouter(prefix="/api/ai")

CONFIG_KEY = "ai_config"
TIMEOUT = 180
PROVIDERS = ("off", "anthropic", "ollama", "openai")

DEFAULTS = {
    "provider": "off",
    "model": "claude-opus-5",
    "base_url": "",          # openai-compatible / ollama override
    "max_tokens": 2000,
}

# Task presets. Each is a system prompt plus whether the reply should be JSON.
TASKS = {
    "code": {
        "system":
            "You write creative-coding implementations for a perceptual "
            "training app. The user describes a visual or sonic goal in "
            "perceptual terms; you return working code and nothing else.\n\n"
            "Rules:\n"
            "- Output ONLY code. No prose, no markdown fences, no explanation.\n"
            "- Match the runtime you are told to target exactly.\n"
            "- Keep it readable: this code is read as a lesson, not just run.\n"
            "- Comment the line where the interesting maths happens, and only "
            "that line.\n"
            "- Prefer the physical form of a falloff or curve over the cheap "
            "approximation, since the point is that the result reads right.",
        "json": False,
    },
    "explain": {
        "system":
            "You explain the mechanism behind a technique to a working "
            "designer who already has hands. Two short paragraphs at most. "
            "Name the actual mechanism rather than restating the effect. "
            "No preamble, no summary sentence at the end.",
        "json": False,
    },
    "critique": {
        "system":
            "You are a coverage checker, not a judge.\n\n"
            "Given a brief and a description of a piece, list concrete things "
            "a client or an art director would flag — hierarchy, contrast, "
            "rhythm, legibility, spectral crowding, accessibility, technical "
            "faults. Aim for things the maker may not have looked at.\n\n"
            "Hard rules:\n"
            "- Do NOT say whether it is good, and do NOT rank options.\n"
            "- Do NOT praise. Every line should be an observation that could "
            "turn into a check.\n"
            "- Each line: the observation, then the mechanism, in that order.\n"
            "- If something cannot be assessed from a text description, say so "
            "rather than guessing.",
        "json": False,
    },
    "brief": {
        "system":
            "You expand a terse creative brief into a structured one: "
            "audience, tone, references, constraints, deliverables, and the "
            "one thing that must be true for it to have worked. Keep the "
            "user's constraint intact and do not soften it — the constraint is "
            "doing the work. Be concrete and short.",
        "json": False,
    },
    "palette": {
        "system":
            "You return colour palettes as JSON and nothing else.\n"
            'Shape: {"name": string, "note": string, '
            '"colors": [{"hex": "#rrggbb", "role": string}]}\n'
            "5 or 6 colours. Roles are things like ground, field, ink, accent, "
            "highlight. Think in opponent terms — decide the lightness "
            "structure first, then the hue relationships. The note says in one "
            "sentence what the palette is doing, mechanically.",
        "json": True,
    },
    "music": {
        "system":
            "You return musical material as JSON and nothing else.\n"
            'Shape: {"name": string, "bpm": number, "note": string, '
            '"tracks": [{"name": string, "instrument": '
            '"synth"|"pluck"|"fm"|"bass"|"drums", '
            '"notes": [{"step": int, "pitch": int, "len": int}]}]}\n'
            "step is a 16th-note index from 0. pitch is a MIDI note number. "
            "len is in 16ths. For a drums track use pitch 36 kick, 38 snare, "
            "42 closed hat, 46 open hat, 45 tom.\n"
            "Stay inside the number of steps you are asked for. Write "
            "something with a rhythmic template that belongs to the requested "
            "genre bundle rather than something generically pleasant.",
        "json": True,
    },
    "freeform": {"system": "Answer concisely and concretely.", "json": False},
}


def load_config() -> dict:
    """Config is global to the install, not per user — it is machine setup."""
    with db.connect() as con:
        r = con.execute("SELECT value FROM kv WHERE user_id=0 AND key=?",
                        (CONFIG_KEY,)).fetchone()
    cfg = dict(DEFAULTS)
    if r:
        try:
            cfg.update(json.loads(r["value"]))
        except json.JSONDecodeError:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    with db.connect() as con:
        con.execute(
            "INSERT INTO kv(user_id,key,value) VALUES(0,?,?) "
            "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
            (CONFIG_KEY, json.dumps(cfg)))


class ConfigIn(BaseModel):
    provider: str = "off"
    model: str = ""
    base_url: str = ""
    api_key: str | None = None      # write-only; never read back
    max_tokens: int = 2000


class CompleteIn(BaseModel):
    task: str = "freeform"
    prompt: str
    context: str = ""
    max_tokens: int | None = None


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"content-type": "application/json",
                                          **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:600]
        raise HTTPException(502, f"{e.code} from the provider: {detail}")
    except urllib.error.URLError as e:
        raise HTTPException(
            502, f"could not reach the provider: {e.reason}. "
                 f"If this is Ollama, check that it is running.")
    except TimeoutError:
        raise HTTPException(504, "the provider timed out")


def complete(cfg: dict, system: str, prompt: str, max_tokens: int) -> str:
    provider = cfg.get("provider", "off")

    if provider == "anthropic":
        key = cfg.get("api_key") or ""
        if not key:
            raise HTTPException(400, "no API key saved for Anthropic")
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            {"model": cfg.get("model") or "claude-opus-5",
             "max_tokens": max_tokens,
             "system": system,
             "messages": [{"role": "user", "content": prompt}]},
            {"x-api-key": key, "anthropic-version": "2023-06-01"})
        parts = [b.get("text", "") for b in data.get("content", [])
                 if b.get("type") == "text"]
        return "".join(parts).strip()

    if provider == "ollama":
        base = (cfg.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
        data = _post_json(
            f"{base}/api/chat",
            {"model": cfg.get("model") or "llama3.1",
             "stream": False,
             "options": {"num_predict": max_tokens},
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": prompt}]},
            {})
        return (data.get("message") or {}).get("content", "").strip()

    if provider == "openai":
        base = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        key = cfg.get("api_key") or ""
        headers = {"authorization": f"Bearer {key}"} if key else {}
        data = _post_json(
            f"{base}/chat/completions",
            {"model": cfg.get("model") or "gpt-4o-mini",
             "max_tokens": max_tokens,
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": prompt}]},
            headers)
        choices = data.get("choices") or []
        return (choices[0]["message"]["content"] if choices else "").strip()

    raise HTTPException(400, "no AI provider is configured")


def _strip_fences(text: str) -> str:
    """Models fence code even when told not to. Take the fence off rather than
    making the caller deal with it."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def register(app, current_user):

    @router.get("/config")
    def get_config(uid: int = Depends(current_user)):
        cfg = load_config()
        return {"provider": cfg["provider"], "model": cfg["model"],
                "base_url": cfg["base_url"], "max_tokens": cfg["max_tokens"],
                "has_key": bool(cfg.get("api_key")),
                "tasks": sorted(TASKS)}

    @router.put("/config")
    def put_config(body: ConfigIn, uid: int = Depends(current_user)):
        if body.provider not in PROVIDERS:
            raise HTTPException(400, "unknown provider")
        cfg = load_config()
        cfg.update({"provider": body.provider, "model": body.model,
                    "base_url": body.base_url,
                    "max_tokens": max(64, min(8000, body.max_tokens))})
        # An omitted key keeps the stored one; an empty string clears it.
        if body.api_key is not None:
            cfg["api_key"] = body.api_key.strip()
        save_config(cfg)
        return {"ok": True, "has_key": bool(cfg.get("api_key"))}

    @router.post("/complete")
    def do_complete(body: CompleteIn, uid: int = Depends(current_user)):
        task = TASKS.get(body.task)
        if not task:
            raise HTTPException(404, "unknown task")
        cfg = load_config()
        if cfg.get("provider", "off") == "off":
            raise HTTPException(400, "AI is switched off — configure a provider "
                                     "in the studio's AI panel first")
        prompt = body.prompt if not body.context else \
            f"{body.context}\n\n---\n\n{body.prompt}"
        limit = body.max_tokens or cfg.get("max_tokens", 2000)
        text = complete(cfg, task["system"], prompt, limit)
        text = _strip_fences(text)
        out = {"text": text, "provider": cfg["provider"], "model": cfg["model"]}
        if task["json"]:
            try:
                out["json"] = json.loads(text)
            except json.JSONDecodeError:
                out["json"] = None
                out["parse_error"] = "the model did not return valid JSON"
        return out

    app.include_router(router)

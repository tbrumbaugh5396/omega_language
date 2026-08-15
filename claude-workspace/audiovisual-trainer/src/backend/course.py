"""The course: markdown modules served straight off disk.

The documents in docs/course are the source of truth and stay ordinary
markdown — they render on GitHub, in an editor, anywhere. This serves them
verbatim so the app never holds a second copy that drifts, and so editing a
file and reloading is the whole authoring loop.

The frontend renders the markdown and swaps any figure reference it has a live
version of for an interactive one, which is why nothing here tries to rewrite
the text.
"""
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from . import config

router = APIRouter(prefix="/api/course")

COURSE_DIR = config.APP_ROOT / "docs" / "course"
FIG_DIR = COURSE_DIR / "figures"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# Title and one-line summary come from the file itself; this is only the order
# and the "core maths" column the course README publishes.
ORDER = [
    ("00-radiometry", "Solid angles, hemisphere integrals"),
    ("01-the-eye", "Inner products, null spaces, linear maps"),
    ("02-colorimetry", "Change of basis, projective geometry, convex hulls"),
    ("03-additive-subtractive", "Vector spaces vs multiplicative algebras"),
    ("04-color-organization", "Cylindrical coordinates, perceptual metrics"),
    ("05-display", "Sampling theory, quantization, transfer functions"),
    ("06-gpu-pipeline", "Homogeneous coordinates, barycentrics, SIMD"),
    ("07-shaders", "Implicit surfaces, noise, filter widths"),
    ("08-web-deliverable", "Budgets, transfer functions, provenance"),
]


def _safe(slug: str) -> Path:
    if not SLUG_RE.match(slug or ""):
        raise HTTPException(400, "bad document name")
    path = (COURSE_DIR / f"{slug}.md").resolve()
    if COURSE_DIR.resolve() not in path.parents:
        raise HTTPException(400, "bad document name")
    if not path.exists():
        raise HTTPException(404, "no such module")
    return path


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def register(app, current_user):

    @router.get("")
    def index(uid: int = Depends(current_user)):
        """The module list, plus whatever else is sitting in the folder."""
        if not COURSE_DIR.exists():
            return {"modules": [], "readme": None, "missing": True}
        listed = {s for s, _ in ORDER}
        modules = []
        for slug, maths in ORDER:
            path = COURSE_DIR / f"{slug}.md"
            if not path.exists():
                continue
            text = path.read_text(errors="replace")
            modules.append({
                "slug": slug,
                "title": _first_heading(text) or slug,
                "maths": maths,
                "words": len(text.split()),
            })
        extra = []
        for path in sorted(COURSE_DIR.glob("*.md")):
            if path.stem in listed or path.stem == "README":
                continue
            extra.append({"slug": path.stem,
                          "title": _first_heading(path.read_text(errors="replace")) or path.stem,
                          "maths": "", "words": 0})
        readme = COURSE_DIR / "README.md"
        return {"modules": modules, "extra": extra,
                "readme": readme.exists(), "missing": False}

    @router.get("/doc/{slug}", response_class=PlainTextResponse)
    def document(slug: str, uid: int = Depends(current_user)):
        return _safe(slug).read_text(errors="replace")

    @router.get("/figure/{name}")
    def figure(name: str, uid: int = Depends(current_user)):
        """Fall back to the generated file when there is no live version."""
        if not SLUG_RE.match(name or ""):
            raise HTTPException(400, "bad figure name")
        path = (FIG_DIR / name).resolve()
        if FIG_DIR.resolve() not in path.parents or not path.exists():
            raise HTTPException(404, "no such figure")
        kind = "image/svg+xml" if path.suffix == ".svg" else "image/png"
        return FileResponse(path, media_type=kind)

    app.include_router(router)

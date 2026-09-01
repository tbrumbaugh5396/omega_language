"""Build a double-clickable "MacroKitchen.app" with a real icon (macOS).

Creates the .app on the Desktop; the app just runs Start MacroKitchen.command.
The browser's own "Install app" menu handles the PWA install once it's open.
"""
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "MacroKitchen"


def make_icns(dest: Path) -> bool:
    """PNG -> .icns via macOS sips/iconutil. Best effort."""
    png = ROOT / "src" / "frontend" / "icons" / "icon-512.png"
    if not png.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_icons.py")])
    if not png.exists() or not shutil.which("iconutil"):
        return False
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "icon.iconset"
        iconset.mkdir()
        for size in (16, 32, 64, 128, 256, 512):
            subprocess.run(
                ["sips", "-z", str(size), str(size), str(png),
                 "--out", str(iconset / f"icon_{size}x{size}.png")],
                capture_output=True)
        r = subprocess.run(["iconutil", "-c", "icns", str(iconset),
                            "-o", str(dest)], capture_output=True)
        return r.returncode == 0


def main() -> None:
    if sys.platform != "darwin":
        print("App-icon launcher is macOS-only; on other platforms use the "
              ".command scripts or your browser's 'Install app' button.")
        return
    app = Path.home() / "Desktop" / f"{APP_NAME}.app"
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    for d in (macos, resources):
        d.mkdir(parents=True, exist_ok=True)

    runner = macos / "run"
    runner.write_text(
        "#!/bin/bash\n"
        f'exec "{ROOT}/command_utilities/Start MacroKitchen.command"\n')
    runner.chmod(0o755)

    have_icon = make_icns(resources / "icon.icns")
    plist = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "local.macro-kitchen",
        "CFBundleVersion": "1.0",
        "CFBundleExecutable": "run",
        "CFBundlePackageType": "APPL",
    }
    if have_icon:
        plist["CFBundleIconFile"] = "icon"
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["touch", str(app)])  # nudge Finder to refresh the icon
    print(f"created {app}")
    print("Tip: once the site is open in Chrome/Safari, use the browser menu's "
          "'Install app…' / 'Add to Dock' for the full PWA experience.")


if __name__ == "__main__":
    main()

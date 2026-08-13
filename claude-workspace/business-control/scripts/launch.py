"""Launch the Business Control server. Writes a pidfile so Stop can find us."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
VENV_BIN = ROOT / ".venv" / "bin"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--https", action="store_true",
                    help="serve TLS with a self-signed cert (needed for PWA "
                         "install from other devices; expect a browser warning)")
    args = ap.parse_args()

    # Re-exec inside the project venv if we're not already in it.
    venv_python = VENV_BIN / "python3"
    if venv_python.exists() and Path(sys.executable).resolve() != venv_python.resolve():
        os.execv(str(venv_python), [str(venv_python), __file__] + sys.argv[1:])

    try:
        import uvicorn
    except ImportError:
        print("Dependencies missing — run 'Install Business Control.command' first.")
        return 1

    from erp.backend import config
    cfg = config.load()
    port = args.port or cfg.get("port", 8860)

    # Make sure icons exist (needed for PWA install).
    icons = ROOT / "src" / "erp" / "frontend" / "icons" / "icon-192.png"
    if not icons.exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_icons.py")])

    ssl_args = {}
    if args.https:
        certdir = config.DATA_DIR / "certs"
        cert, key = certdir / "cert.pem", certdir / "key.pem"
        if not (cert.exists() and key.exists()):
            import shutil
            import subprocess
            if not shutil.which("openssl"):
                print("openssl not found — cannot create a self-signed cert.")
                return 1
            certdir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", str(key), "-out", str(cert), "-days", "825",
                 "-subj", "/CN=business-control.local",
                 "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                check=True, capture_output=True)
            print(f"generated self-signed cert in {certdir}")
        ssl_args = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}

    pidfile = config.DATA_DIR / "server.pid"
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(os.getpid()))
    scheme = "https" if args.https else "http"
    print(f"Business Control → {scheme}://{args.host}:{port}  (pid {os.getpid()})")
    try:
        uvicorn.run("erp.backend.main:app", host=args.host, port=port,
                    log_level="info", **ssl_args)
    finally:
        pidfile.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

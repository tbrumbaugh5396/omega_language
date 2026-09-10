"""Launch the Business Control server. Writes a pidfile so Stop can find us."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
VENV_BIN = ROOT / ".venv" / "bin"


def lan_ip() -> str:
    """The address this machine has on its network — what a phone on the
    same wifi types. Best guess by asking the routing table, never a
    packet sent."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:                                        # noqa: BLE001
        return "127.0.0.1"


def cert_sans(ip: str) -> str:
    """Every name the self-signed cert should answer to: localhost, the
    loopback, and the LAN address — the one a phone actually uses. A cert
    that names only localhost makes every phone's browser call the site
    an impostor."""
    names = ["DNS:localhost", "DNS:*.localhost", "IP:127.0.0.1"]
    if ip and ip != "127.0.0.1":
        names.append(f"IP:{ip}")
    return ",".join(names)


def cert_covers(cert: Path, ip: str) -> bool:
    """Does the cert on disk already name this address? Read from the
    certificate itself; a note beside it could be wrong."""
    import shutil
    import subprocess
    if not shutil.which("openssl"):
        return True
    try:
        out = subprocess.run(["openssl", "x509", "-in", str(cert), "-noout",
                              "-text"], capture_output=True, text=True,
                             check=True).stdout
    except subprocess.CalledProcessError:
        return False
    return ip == "127.0.0.1" or f"IP Address:{ip}" in out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument(
        "--reload", action="store_true",
        help="restart when a source file under src/ changes. Off by "
             "default because a restart drops every websocket, and "
             "because a save mid-edit can restart on a half-written "
             "file. On, a new route works without anybody "
             "remembering to restart — which is the failure this "
             "exists for: a screen added after the server started "
             "answers 404 and reads as a bug in the screen.")
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

    ip = lan_ip()
    ssl_args = {}
    if args.https:
        certdir = config.DATA_DIR / "certs"
        cert, key = certdir / "cert.pem", certdir / "key.pem"
        # Made once, and made again when the machine's address has moved
        # since — a cert that names last week's wifi is no use on this one.
        if not (cert.exists() and key.exists()) or not cert_covers(cert, ip):
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
                 "-addext", "subjectAltName=" + cert_sans(ip)],
                check=True, capture_output=True)
            print(f"generated self-signed cert in {certdir} for {cert_sans(ip)}")
        ssl_args = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    # The app builds every outward link — QR codes, class invites, sign-in
    # links — from these, so an HTTPS server hands out https links and a
    # server on an unusual port hands out that port.
    os.environ["BC_SCHEME"] = "https" if args.https else "http"
    os.environ["BC_PORT"] = str(port)

    pidfile = config.DATA_DIR / "server.pid"
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(os.getpid()))
    scheme = "https" if args.https else "http"
    print(f"Business Control → {scheme}://{args.host}:{port}  (pid {os.getpid()})")
    if args.host in ("0.0.0.0", "::") and ip != "127.0.0.1":
        print(f"  on the wifi → {scheme}://{ip}:{port}   (phones on the same "
              f"network; tenants by host alias, see CLAUDE.md)")
    if args.reload:
        # Watch the source only. Watching the whole tree means every order,
        # every uploaded photo and every WAL checkpoint restarts the
        # server, which is worse than not reloading at all.
        ssl_args["reload"] = True
        ssl_args["reload_dirs"] = [str(ROOT / "src")]
        print("  reloading on changes under src/ — websockets drop on each")
    try:
        uvicorn.run("erp.backend.main:app", host=args.host, port=port,
                    log_level="info", **ssl_args)
    finally:
        pidfile.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

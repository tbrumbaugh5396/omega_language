"""Serves this folder and accepts POST /save/<name> to write a file.

Only reason it exists: rendering the brand SVG needs a real SVG engine, the
machine has no cairo/rsvg, and the browser already has one. So the page
rasterises the logo and hands the bytes back here rather than me
re-implementing path rendering or settling for a downscaled screenshot.
"""
import http.server, pathlib, re, socketserver

HERE = pathlib.Path(__file__).parent

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def do_POST(self):
        m = re.fullmatch(r"/save/([\w.-]+)", self.path)
        if not m:
            self.send_error(404); return
        n = int(self.headers.get("Content-Length", 0))
        (HERE / m.group(1)).write_bytes(self.rfile.read(n))
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", 8899), H) as s:
    s.serve_forever()

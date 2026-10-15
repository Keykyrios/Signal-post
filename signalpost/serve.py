"""Serve the built React viewer (ui/dist) and the run output (out/) under /data."""

import functools
import http.server
import os
import posixpath
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "ui", "dist")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, out_dir, **kwargs):
        self.out_dir = out_dir
        super().__init__(*args, directory=DIST, **kwargs)

    def translate_path(self, path):
        path = posixpath.normpath(urllib.parse.unquote(path.split("?", 1)[0].split("#", 1)[0]))
        if path.startswith("/data/"):
            rel = path[len("/data/"):]
            full = os.path.normpath(os.path.join(self.out_dir, rel))
            if full.startswith(os.path.abspath(self.out_dir) + os.sep):
                return full
            return os.path.join(DIST, "__blocked__")
        return super().translate_path(path)

    def log_message(self, *args):
        pass


def serve(out_dir="out", port=8000):
    if not os.path.isfile(os.path.join(DIST, "index.html")):
        raise SystemExit("ui/dist is missing. Build it once with: cd ui && npm install && npm run build")
    out_dir = os.path.abspath(out_dir)
    handler = functools.partial(Handler, out_dir=out_dir)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Signalpost viewer: http://127.0.0.1:{port}/  (data from {out_dir})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Stopped.")

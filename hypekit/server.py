"""Local HTTP API + the web UI (stdlib). Binds 127.0.0.1 only.

    python -m hypekit serve [--port 8765]

JSON (GET):
  /api/info                                    catalog meta + version
  /api/find?q=                                 {sounds, lines, textures}
  /api/sounds?q=&kind=&level=&speaker=&limit=&offset=
  /api/lines?q=&level=&speaker=&common=1&limit=&offset=
  /api/textures?q=&archive=&limit=&offset=
  /api/levels                                  levels with line counts and place names
  /api/script/<level>                          lines of a level with their voice sound ids
  /api/persos?q=&level=&all=1                  {status: character scan progress, items: records or null}
  /api/perso/<id>                              one character + its animated states
  /api/saves, /api/save/<slot>                 save slots; one slot in full (stats, inventory, flags)
  /api/get/<id>                                one record + links
  /api/schema                                  JSON Schema of the records
Payloads: /api/wav/<id> (audio/wav, Range supported), /api/png/<id>?mip=0 (image/png),
  /api/glb/<perso id>?state=N (model/gltf-binary; default state = the initial one).
Errors: {"error": text} with 404 (no record) / 422 (cannot decode here) / 400.
Everything else is a static file of hypekit/web/.
"""
import json
import mimetypes
import os
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import hypekit
from . import schema

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
MAX_LIMIT = 1000


class _Cache:
    """Last few payloads (WAV decode of a track can take a second)."""

    def __init__(self, n=16):
        self.n, self.d, self.lock = n, {}, threading.Lock()

    def get(self, k, make):
        with self.lock:
            if k in self.d:
                v = self.d.pop(k)
                self.d[k] = v
                return v
        v = make()
        with self.lock:
            self.d[k] = v
            while len(self.d) > self.n:
                self.d.pop(next(iter(self.d)))
        return v


def make_handler(kit):
    payloads = _Cache()

    class H(BaseHTTPRequestHandler):
        server_version = f'hypekit/{hypekit.__version__}'

        def log_message(self, fmt, *args):          # quiet
            pass

        def _send(self, code, body, ctype, extra=None):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'max-age=3600' if self.path.startswith(('/api/wav/', '/api/png/', '/api/glb/'))
                             else 'no-cache')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

        def _bytes(self, data, ctype):
            rng = self.headers.get('Range', '')
            if rng.startswith('bytes='):
                a, _, b = rng[6:].partition('-')
                try:
                    start = int(a) if a else max(0, len(data) - int(b))
                    end = min(int(b), len(data) - 1) if a and b else len(data) - 1
                except ValueError:
                    start, end = 0, len(data) - 1
                if start >= len(data):
                    return self._send(416, b'', ctype, {'Content-Range': f'bytes */{len(data)}'})
                return self._send(206, data[start:end + 1], ctype,
                                  {'Content-Range': f'bytes {start}-{end}/{len(data)}', 'Accept-Ranges': 'bytes'})
            self._send(200, data, ctype, {'Accept-Ranges': 'bytes'})

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(u.query).items()}
            path = unquote(u.path)
            try:
                if path.startswith('/api/'):
                    return self._api(path[5:], q)
                return self._static(path)
            except hypekit.NotFound as ex:
                self._json({'error': f'no record {ex}'}, 404)
            except hypekit.NotAvailable as ex:
                self._json({'error': str(ex)}, 422)
            except (ValueError, KeyError) as ex:
                self._json({'error': f'bad request: {ex}'}, 400)
            except BrokenPipeError:
                pass
            except Exception as ex:                     # noqa: BLE001 - report, keep serving
                traceback.print_exc()
                self._json({'error': f'{type(ex).__name__}: {ex}'}, 500)

        def _api(self, p, q):
            lim = min(int(q.get('limit') or 200), MAX_LIMIT)
            off = int(q.get('offset') or 0)
            name, _, arg = p.partition('/')
            if name == 'info':
                m = kit.meta()
                m.update(version=hypekit.__version__, schema_version=schema.VERSION, discs=kit.discs,
                         vgmstream=bool(kit.library.vgmstream))
                return self._json(m)
            if name == 'find':
                return self._json(kit.find(q.get('q', ''), min(lim, 50)))
            if name == 'sounds':
                return self._json(kit.sounds(q.get('q', ''), q.get('kind'), q.get('level'), q.get('speaker'),
                                             lim, off))
            if name == 'lines':
                return self._json(kit.lines(q.get('q', ''), q.get('level'), q.get('speaker'),
                                            q.get('common') == '1', lim, off))
            if name == 'textures':
                return self._json(kit.textures(q.get('q', ''), q.get('archive'), lim, off))
            if name == 'levels':
                return self._json(kit.levels())
            if name == 'script':
                return self._json(kit.script(arg))
            if name == 'get':
                return self._json(kit.get(arg))
            if name == 'schema':
                return self._json(schema.json_schema())
            if name == 'persos':
                st = kit.persos_status()
                items = kit.persos(q.get('q', ''), q.get('level'), q.get('all') != '1') if st['state'] == 'ready' else None
                return self._json(dict(status=st, items=items))
            if name == 'perso':
                return self._json(kit.perso(arg))
            if name == 'glb':
                state = int(q['state']) if q.get('state') not in (None, '') else None
                return self._bytes(payloads.get(('glb', arg, state), lambda: kit.glb(arg, state)), 'model/gltf-binary')
            if name == 'saves':
                return self._json(kit.saves())
            if name == 'save':
                return self._json(kit.save(arg))
            if name == 'wav':
                return self._bytes(payloads.get(('wav', arg), lambda: kit.wav(arg)), 'audio/wav')
            if name == 'png':
                mip = int(q.get('mip') or 0)
                return self._bytes(payloads.get(('png', arg, mip), lambda: kit.png(arg, mip)), 'image/png')
            self._json({'error': f'unknown endpoint /api/{name}'}, 404)

        def _static(self, path):
            root = os.path.realpath(WEB)
            f = os.path.realpath(os.path.join(root, path.lstrip('/') or 'index.html'))
            if os.path.commonpath([root, f]) != root or not os.path.isfile(f):
                f = os.path.join(WEB, 'index.html')     # single-page app
            with open(f, 'rb') as fh:
                data = fh.read()
            ctype = mimetypes.guess_type(f)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype.endswith('javascript'):
                ctype += '; charset=utf-8'
            self._send(200, data, ctype)

    return H


def serve(kit, port=0, host='127.0.0.1'):
    """Start the server in a background thread; -> (server, url)."""
    mimetypes.add_type('text/javascript', '.js')
    srv = ThreadingHTTPServer((host, port), make_handler(kit))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name='hypekit-http').start()
    return srv, f'http://{host}:{srv.server_address[1]}/'

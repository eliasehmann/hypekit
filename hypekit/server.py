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
  /api/game                                    the open game folder (+ the saved one); POST /api/game, /api/game/browse
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


class Holder:
    """The open game (or None until the user picks a folder); switch() opens another install without a restart."""

    def __init__(self, kit, cache=None, discs=None, vgmstream=None):
        self.kit, self.cache, self.discs, self.vgmstream = kit, cache, discs, vgmstream
        self.payloads = _Cache()
        self.lock = threading.Lock()

    def switch(self, folder):
        from . import game as G
        folder = os.path.abspath(os.path.expanduser((folder or '').strip().strip('"')))
        if not G.is_game(folder):
            raise ValueError(f'{folder} is not a Hype: The Time Quest folder (it needs Gamedata\\World\\Sound and Levels)')
        with self.lock:
            new = hypekit.open(folder, self.cache, self.discs, self.vgmstream)
            new.build()
            G.save_settings(game=new.game.root)
            old, self.kit = self.kit, new
            self.payloads = _Cache()
        if old and old is not new:
            old.close()
        return new.game.root


_DIALOG = threading.Lock()


def pick_folder(initial=None):
    """Native folder dialog on this machine (the server is local); -> folder or None."""
    from tkinter import Tk, filedialog
    with _DIALOG:
        root = Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        try:
            return filedialog.askdirectory(parent=root, title='Choose the Hype: The Time Quest folder',
                                           initialdir=initial or os.path.expanduser('~'), mustexist=True) or None
        finally:
            root.destroy()


def make_handler(holder):

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

        def do_POST(self):
            """POST /api/zip  {"ids": [...], "name": "x"} -> application/zip (sounds as WAV, textures as PNG, models as GLB).
            POST /api/game {"folder": "..."} -> open that install;  POST /api/game/browse -> folder dialog, then open it."""
            try:
                path = urlparse(self.path).path
                n = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(min(n, 4 << 20)) or b'{}')
                if path in ('/api/game', '/api/game/browse'):
                    folder = body.get('folder')
                    if path.endswith('browse'):
                        start = holder.kit.game.root if holder.kit else body.get('folder')
                        folder = pick_folder(start)
                        if not folder:
                            return self._json({'cancelled': True})
                    try:
                        return self._json({'game': holder.switch(folder)})
                    except (ValueError, FileNotFoundError) as ex:
                        return self._json({'error': str(ex), 'folder': folder}, 400)
                if path != '/api/zip':
                    return self._json({'error': 'unknown endpoint'}, 404)
                if not holder.kit:
                    return self._json({'error': 'Choose the game folder first', 'needs_game': True}, 409)
                data = make_zip(holder.kit, body.get('ids') or [], body.get('state'))
                name = ''.join(c for c in (body.get('name') or 'hype') if c.isalnum() or c in '-_ ').strip() or 'hype'
                self._send(200, data, 'application/zip', {'Content-Disposition': f'attachment; filename="{name}.zip"'})
            except (ValueError, KeyError) as ex:
                self._json({'error': f'bad request: {ex}'}, 400)
            except Exception as ex:                     # noqa: BLE001
                traceback.print_exc()
                self._json({'error': f'{type(ex).__name__}: {ex}'}, 500)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
            path = unquote(u.path)
            kit = holder.kit
            try:
                if path.startswith('/api/') and kit is None and path not in ('/api/info', '/api/game'):
                    return self._json({'error': 'Choose the game folder first', 'needs_game': True}, 409)
                if path.startswith('/api/q/'):
                    return self._json(query(kit, path[7:], q))
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
            kit, payloads = holder.kit, holder.payloads
            lim = min(int(q.get('limit') or 200), MAX_LIMIT)
            off = int(q.get('offset') or 0)
            name, _, arg = p.partition('/')
            if name == 'game':
                from . import game as G
                return self._json(dict(game=kit.game.root if kit else None, saved=G.settings().get('game'),
                                       env=os.environ.get(G.ENV_GAME), cache=kit.cache_dir if kit else None))
            if name == 'info' and kit is None:
                return self._json(dict(needs_game=True, version=hypekit.__version__))
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


FILTERS = {'sounds': ('q', 'kind', 'level', 'speaker', 'format', 'length', 'loop', 'group', 'ids'),
           'lines': ('q', 'level', 'speaker', 'voiced', 'common', 'ids'),
           'textures': ('q', 'archive', 'format', 'folder', 'size', 'alpha', 'ids'),
           'persos': ('q', 'level', 'category', 'ids')}


def query(kit, table, q):
    """/api/q/<table>?<filters>&sort=&limit=&offset=&facets=1 -> {items, total, facets?} (see query.py)."""
    from . import query as Q
    if table not in FILTERS:
        raise KeyError(table)
    f = {k: q[k] for k in FILTERS[table] if k in q}
    if 'ids' in q:
        f['ids'] = q['ids']                       # '' = nothing starred yet: an empty result, not "no filter"
    lim, off, sort = min(int(q.get('limit') or 120), MAX_LIMIT), int(q.get('offset') or 0), q.get('sort', '')
    if table == 'persos':
        st = kit.persos_status()
        if st['state'] != 'ready':
            return dict(status=st, items=None, total=0)
        r = Q.persos(kit.scanner.records, f, sort)
        r['items'] = r['items'][off:off + lim]
        r['status'] = st
        return r
    r = getattr(Q, table)(kit, f, lim, off, sort)
    if q.get('facets') == '1':
        r['facets'] = getattr(Q, table[:-1] + '_facets')(kit, f)
    return r


def make_zip(kit, ids, state=None):
    """ZIP bytes of the payloads of ids (max 500): sound -> .wav, texture -> .png, character -> .glb."""
    import io
    import zipfile
    buf = io.BytesIO()
    names = set()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for rid in ids[:500]:
            try:
                if rid.split(':')[0] in ('Textures', 'Vignette'):
                    r = kit.get(rid)
                    name, data = r['path'].replace('/', '_').rsplit('.', 1)[0] + '.png', kit.png(rid)
                elif rid.startswith(('Bnk_', 'apm:')):
                    name, data = kit.sound(rid).file_name(), kit.wav(rid)
                else:
                    rec = next((r for r in (kit.scanner.records or []) if r['id'] == rid), None)
                    base = (rec['name'] if rec and rec['name'] else rid.replace(':', '_'))
                    name, data = f'{base}.glb', kit.glb(rid, state)
            except (hypekit.NotFound, hypekit.NotAvailable, KeyError, ValueError) as ex:
                name, data = rid.replace(':', '_') + '.error.txt', str(ex).encode('utf-8')
            stem, ext = name.rsplit('.', 1) if '.' in name else (name, '')
            k = 2
            while name in names:
                name = f'{stem} ({k}).{ext}'
                k += 1
            names.add(name)
            z.writestr(name, data, compress_type=zipfile.ZIP_STORED if ext in ('png', 'glb') else zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def serve(kit, port=0, host='127.0.0.1', cache=None, discs=None, vgmstream=None):
    """Start the server in a background thread (kit may be None: the UI then asks for the game folder);
    -> (server, url); server.holder.kit is the open game."""
    mimetypes.add_type('text/javascript', '.js')
    holder = Holder(kit, cache, discs, vgmstream)
    srv = ThreadingHTTPServer((host, port), make_handler(holder))
    srv.holder = holder
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name='hypekit-http').start()
    return srv, f'http://{host}:{srv.server_address[1]}/'

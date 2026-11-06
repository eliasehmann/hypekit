"""hypekit command line: the same calls as the Python API, JSON with --json (for agents and scripts).

    python -m hypekit info                               install, catalog counts
    python -m hypekit find <query>                       search sounds, lines, textures
    python -m hypekit sounds [query] [--kind voice] [--level brigand2] [--speaker RAJOTH]
    python -m hypekit lines  [query] [--level brigand2] [--speaker RAJOTH] [--common]
    python -m hypekit textures [query] [--archive Vignette]
    python -m hypekit levels
    python -m hypekit script <level>                     a level's dialogue in order, with voice sound ids
    python -m hypekit persos [query] [--level fort] [--all]   characters (first run scans all levels, ~2 min)
    python -m hypekit glb <perso id> [--state N] [--out FILE]   one character as .glb
    python -m hypekit saves | save <slot>               save slots / one slot in full
    python -m hypekit get <id>                           one record + links
    python -m hypekit export <id> [<id> ...] [--out DIR] .wav / .png
    python -m hypekit sql "<SELECT ...>"                 read-only SQL on the catalog
    python -m hypekit schema [sound|line|texture]        JSON Schema of the records
    python -m hypekit build [--force]                    (re)build the catalog
    python -m hypekit serve [--port 8765]                local HTTP API + web UI (server.py)
    python -m hypekit app [--browser]                    the desktop app (app.py)
Options: --game DIR, --disc DIR (repeatable; .csb sound names), --cache DIR, --limit N (default 50), --json.
Without --json: a short table (id, then the main field) and a count.
"""
import argparse
import json
import os
import sys
import time

import hypekit
from . import schema

MAIN = {'sound': ('kind', 'title'), 'line': ('level', 'speaker', 'text'), 'texture': ('format', 'path')}


def _table(rows, kind, out):
    cols = MAIN[kind]
    for r in rows:
        cells = [str(r.get(c) if r.get(c) is not None else '') for c in cols]
        if kind == 'texture':
            cells.insert(1, f"{r['width']}x{r['height']}")
        if kind == 'sound' and r.get('seconds') is not None:
            cells.insert(1, f"{r['seconds']:.1f}s")
        out.write(f"{r['id']:<16} " + '  '.join(c[:90] for c in cells) + '\n')


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)          # global options, allowed before or after the command
    common.add_argument('--game', default=argparse.SUPPRESS)
    common.add_argument('--disc', action='append', default=argparse.SUPPRESS)
    common.add_argument('--cache', default=argparse.SUPPRESS)
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    common.add_argument('--limit', type=int, default=argparse.SUPPRESS)
    ap = argparse.ArgumentParser(prog='hypekit', description='Read Hype: The Time Quest game data.', parents=[common])
    sub = ap.add_subparsers(dest='cmd', required=True)
    _add = sub.add_parser
    sub.add_parser = lambda name, **kw: _add(name, parents=[common], **kw)
    sub.add_parser('info')
    p = sub.add_parser('find')
    p.add_argument('query')
    for name in ('sounds', 'lines', 'textures'):
        p = sub.add_parser(name)
        p.add_argument('query', nargs='?', default='')
        if name == 'sounds':
            p.add_argument('--kind')
        if name != 'textures':
            p.add_argument('--level')
            p.add_argument('--speaker')
        if name == 'lines':
            p.add_argument('--common', action='store_true')
        if name == 'textures':
            p.add_argument('--archive')
    sub.add_parser('levels')
    p = sub.add_parser('script')
    p.add_argument('level')
    p = sub.add_parser('persos')
    p.add_argument('query', nargs='?', default='')
    p.add_argument('--level')
    p.add_argument('--all', action='store_true')
    sub.add_parser('saves')
    p = sub.add_parser('save')
    p.add_argument('slot')
    p = sub.add_parser('glb')
    p.add_argument('id')
    p.add_argument('--state', type=int)
    p.add_argument('--out')
    p = sub.add_parser('get')
    p.add_argument('id')
    p = sub.add_parser('export')
    p.add_argument('ids', nargs='+')
    p.add_argument('--out', default='.')
    p = sub.add_parser('sql')
    p.add_argument('query')
    p = sub.add_parser('schema')
    p.add_argument('kind', nargs='?', choices=sorted(schema.RECORDS))
    p = sub.add_parser('serve')
    p.add_argument('--port', type=int, default=8765)
    p = sub.add_parser('app')
    p.add_argument('--browser', action='store_true')
    p = sub.add_parser('build')
    p.add_argument('--force', action='store_true')
    a = ap.parse_args(argv)
    for k, v in dict(game=None, disc=None, cache=None, json=False, limit=50).items():
        if not hasattr(a, k):
            setattr(a, k, v)

    out = sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')

    def emit(obj):
        out.write(json.dumps(obj, ensure_ascii=False, indent=1 if not isinstance(obj, list) else None) + '\n')

    if a.cmd == 'schema':
        emit(schema.json_schema(a.kind))
        return 0
    try:
        kit = hypekit.open(a.game, a.cache, a.disc)
    except FileNotFoundError as ex:
        if a.cmd == 'app':                           # the desktop app opens on its "choose the game folder" screen
            from . import app
            return app.run(None, a.browser, cache=a.cache, discs=a.disc)
        sys.stderr.write(f'hypekit: {ex}\n')
        return 2
    lim = a.limit or None
    try:
        if a.cmd in ('info', 'build'):
            m = kit.build(force=getattr(a, 'force', False))
            m.update(version=hypekit.__version__, cache=kit.cache_dir, discs=kit.discs,
                     vgmstream=kit.library.vgmstream if a.cmd == 'build' else None)
            emit(m)
        elif a.cmd == 'find':
            r = kit.find(a.query, lim)
            if a.json:
                emit(r)
            else:
                for k, rows in r.items():
                    out.write(f'-- {k}: {len(rows)}{"+" if lim and len(rows) == lim else ""}\n')
                    _table(rows, k[:-1], out)
        elif a.cmd in ('sounds', 'lines', 'textures'):
            kw = {k: getattr(a, k) for k in ('kind', 'level', 'speaker', 'common', 'archive') if hasattr(a, k)}
            rows = getattr(kit, a.cmd)(a.query, limit=lim, **kw)
            if a.json:
                emit(rows)
            else:
                _table(rows, a.cmd[:-1], out)
                out.write(f'{len(rows)} {a.cmd}{" (limit, use --limit 0 for all)" if lim and len(rows) == lim else ""}\n')
        elif a.cmd == 'script':
            rows = kit.script(a.level)
            if a.json:
                emit(rows)
            else:
                for r in rows:
                    voice = f"  [{', '.join(r['sounds'])}]" if r['sounds'] else ''
                    out.write(f"{r['id']:<14} {r['speaker'] or '-':<12} {r['text'][:110]}{voice}\n")
                out.write(f'{len(rows)} lines\n')
        elif a.cmd == 'levels':
            rows = kit.levels()
            if a.json:
                emit(rows)
            else:
                for r in rows:
                    out.write(f"{r['level']:<12} {r['lines']:>4} lines  {r['place']}\n")
        elif a.cmd == 'persos':
            if kit.persos_status(start=False)['state'] != 'ready':
                sys.stderr.write('hypekit: scanning all levels for characters (once, ~2 min)...\n')
            rows = kit.persos(a.query, a.level, not a.all, wait=True)
            rows = rows[:lim] if lim else rows
            if a.json:
                emit(rows)
            else:
                for r in rows:
                    out.write(f"{r['id']:<22} {r['name'] or '-':<28} {r['states']:>4} states  {r['parts']:>4} parts\n")
                out.write(f'{len(rows)} characters\n')
        elif a.cmd == 'glb':
            path = a.out or f"{a.id.replace(':', '_')}{'' if a.state is None else '_' + str(a.state)}.glb"
            with open(path, 'wb') as f:
                f.write(kit.glb(a.id, a.state))
            emit([path]) if a.json else out.write(path + '\n')
        elif a.cmd == 'saves':
            rows = kit.saves()
            if a.json:
                emit(rows)
            else:
                for r in rows:
                    t = r['playtime'] or 0
                    out.write(f"{r['id']:<11} {r['place'] + ' (' + r['level'] + ')':<34} {t // 3600}:{t // 60 % 60:02d} "
                              f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['modified']))}\n")
        elif a.cmd == 'save':
            emit(kit.save(a.slot))
        elif a.cmd == 'get':
            emit(kit.get(a.id))
        elif a.cmd == 'export':
            os.makedirs(a.out, exist_ok=True)
            done = [kit.export(rid, a.out) for rid in a.ids]
            emit(done) if a.json else out.write('\n'.join(done) + '\n')
        elif a.cmd == 'serve':
            from . import server
            kit.build()
            srv, url = server.serve(kit, a.port, cache=a.cache, discs=a.disc)
            out.write(f'hypekit: serving {url}  (Ctrl+C to stop)\n')
            out.flush()
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                srv.shutdown()
                srv.server_close()
        elif a.cmd == 'app':
            from . import app
            return app.run(kit, a.browser, cache=a.cache, discs=a.disc)
        elif a.cmd == 'sql':
            if not a.query.lstrip().lower().startswith(('select', 'with', 'pragma')):
                sys.stderr.write('hypekit: sql is read-only (SELECT / WITH / PRAGMA)\n')
                return 2
            emit(kit.sql(a.query))
    except hypekit.NotFound as ex:
        sys.stderr.write(f'hypekit: no record {ex}\n')
        return 1
    except hypekit.NotAvailable as ex:
        sys.stderr.write(f'hypekit: {ex}\n')
        return 1
    finally:
        kit.close()
    return 0

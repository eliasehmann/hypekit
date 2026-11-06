"""Readable names for Hype's sounds, built from the install itself.

Output (cache): <cache>/names_<stamp>.json, stamp = sizes/mtimes of the banks, .snd, .lng and .csb files.

Sources (all in the install, so names follow the install's language):
  banks   section1 = events (0x20 B: +4 kind 1 play / 2 stop, +8 node), section2 = nodes (0x5c B, type 1 audio,
          10 random, 11 sequence, 8 switch; lists at section2 end + entry +0x10). node/event id = bank << 16 | index.
  .snd    <level>.snd / Fix.snd = (u32 event, u32 address) pairs: the events a level uses -> "used in" levels.
  .lng    module 0x14 = lip-sync records (+0x14 voice event, patched in from the .snd), module 0x15 block 0 = dialogs
          (pointer to lip record +8, dialog name); the dialog text (speaker + line) via hypekit.text.
Sequence nodes chain parts into one sound (music is stored as many MPEG pieces; long voice lines too): they become
"tracks" that the browser plays as one.
"""
import glob
import json
import os
import re
import struct
import sys

from . import bnm, csb, sna, text

VERSION = 4                  # 3: text reader keeps accented lines, 4: letter-based junk filter

PLACES = [   # website-tools/wiki/places.md
    ("Gogoud's Manor", 'manoir manoir2 manoir3 manoir4'), ('The Forest', 'brigand brigand2 brigand3 brigand4'),
    ('The Brigand Village', 'village2 village3 village4'), ('The Town of Torras', 'toras toras2 toras3 toras4'),
    ('The Fortress', 'fort fort3 fort4'), ('The Dungeons', 'cachots cachots4'),
    ('The Monastery', 'monast1 monast2 monast3'), ('The Laboratories', 'labo labo3'), ('The Astrolabe', 'astrolabe'),
    ('The Field of Courage', 'casino casino3'), ('The Sky', 'ciel1 ciel2 ciel3 ciel4'),
    ('The Lost City', 'cite3 cite4'), ('The Black Tower', 'tour3 tour toptower')]
PLACE = {lv: p for p, lvs in PLACES for lv in lvs.split()}
PLACE['Fix'] = 'Everywhere'


def place_of(lv):
    return PLACE.get(lv, lv)


def level_label(lv):
    """'The Forest (brigand2)'"""
    if lv == 'Fix':
        return 'Everywhere (Fix)'
    return f'{place_of(lv)} ({lv})' if lv in PLACE else lv


class Banks:
    def __init__(self, sound_dir):
        self.dir = sound_dir
        self._b = {}

    def get(self, n):
        if n not in self._b:
            p = os.path.join(self.dir, f'Bnk_{n}.bnm')
            if os.path.exists(p):
                b = open(p, 'rb').read()
                h = struct.unpack_from('<11I', b, 0)
                self._b[n] = (b, h, h[3] + h[4] * 0x5c)
            else:
                self._b[n] = None
        return self._b[n]

    def event_node(self, ev):
        bk = self.get(ev >> 16)
        if not bk or (ev & 0xffff) >= bk[1][2]:
            return None
        return struct.unpack_from('<I', bk[0], bk[1][1] + (ev & 0xffff) * 0x20 + 8)[0]

    def node(self, key):
        """-> (type, [child keys]) ; audio = (1, [])"""
        bk = self.get(key >> 16)
        if not bk or (key & 0xffff) >= bk[1][4]:
            return None
        b, h, xs = bk
        o = h[3] + (key & 0xffff) * 0x5c
        w = struct.unpack_from('<10I', b, o)
        t, lst = w[1], xs + w[4]
        try:
            if t == 10:
                return t, [struct.unpack_from('<I', b, lst + i * 12)[0] for i in range(w[6])]
            if t == 11:
                return t, [struct.unpack_from('<I', b, lst + i * 24)[0] for i in range(w[9])]
            if t == 8:
                return t, [struct.unpack_from('<I', b, lst + i * 8 + 4)[0] for i in range(w[8])]
        except struct.error:
            return t, []
        return t, []

    def leaves(self, key, depth=0):
        """Audio node keys under key, in play order (all random/switch variants)."""
        n = self.node(key)
        if not n or depth > 8:
            return []
        if n[0] == 1:
            return [key]
        return [x for c in n[1] for x in self.leaves(c, depth + 1)]


def install_root(sound_dir):
    """<root>\\Gamedata\\World\\Sound -> <root>"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sound_dir))))


def csb_files(sound_dir, extra=()):
    return csb.find(csb.default_folders(install_root(sound_dir), extra))


def stamp(sound_dir, extra=()):
    levels = os.path.join(os.path.dirname(sound_dir), 'Levels')
    fs = glob.glob(os.path.join(sound_dir, '*.bnm')) + glob.glob(os.path.join(levels, '*', '*.snd')) + \
        glob.glob(os.path.join(levels, '*', '*.lng')) + glob.glob(os.path.join(levels, 'Fix.*')) + csb_files(sound_dir, extra)
    h = VERSION
    for f in sorted(fs):
        st = os.stat(f)
        h = (h * 1000003 + st.st_size * 31 + int(st.st_mtime)) & 0xffffffffffff
    return f'{h:012x}'


def voices(levels, lv):
    """{voice event: dialog name} of one level (gen_voices.py logic)."""
    lng = os.path.join(levels, lv, lv + '.lng')
    snd = os.path.join(levels, lv, lv + '.snd')
    if not (os.path.exists(lng) and os.path.exists(snd)):
        return {}
    lip = dlg = None
    for m, b, base, data in sna.read_sna(lng):
        if data and m == 0x14:
            lip = (base & 0xffffffff, data)
        if data and m == 0x15 and b == 0:
            dlg = (base & 0xffffffff, data)
    if not lip or not dlg:
        return {}
    lb, ld = lip
    s = open(snd, 'rb').read()
    ev_at = {}
    for o in range(0, len(s) - 7, 8):
        ev, addr = struct.unpack_from('<II', s, o)
        if lb <= addr < lb + len(ld):
            ev_at[addr - 0x14 + 8] = ev
    _, dd = dlg
    out = {}
    for o in range(0, len(dd) - 11, 4):
        p = struct.unpack_from('<I', dd, o)[0]
        if not (lb <= p < lb + len(ld)) or struct.unpack_from('<I', dd, o + 4)[0] > 64:
            continue
        e = dd.find(b'\0', o + 8)
        name = dd[o + 8:e].decode('latin-1')
        if name and name.replace('_', '').isalnum() and p in ev_at:
            out.setdefault(ev_at[p], name)
    return out


def texts(levels, lv):
    """{dialog name: (speaker, line)} of one level."""
    lng = os.path.join(levels, lv, lv + '.lng')
    if not os.path.exists(lng):
        return {}
    out = {}
    for seq, who, line in text.turns(text.fragments(lng)):
        if seq and seq not in out:
            out[seq] = (who, line)
    return out


def build(sound_dir, progress=None, extra=()):
    levels = os.path.join(os.path.dirname(sound_dir), 'Levels')
    bk = Banks(sound_dir)
    lvs = sorted(d for d in os.listdir(levels) if os.path.exists(os.path.join(levels, d, d + '.snd'))) \
        if os.path.isdir(levels) else []
    used = {}                    # node key -> set of levels
    events = {}                  # level -> [event]
    for i, lv in enumerate(['Fix'] + lvs):
        p = os.path.join(levels, 'Fix.snd') if lv == 'Fix' else os.path.join(levels, lv, lv + '.snd')
        if not os.path.exists(p):
            continue
        s = open(p, 'rb').read()
        evs = sorted({struct.unpack_from('<I', s, o)[0] for o in range(0, len(s) - 7, 8)})
        events[lv] = evs
        for ev in evs:
            n = bk.event_node(ev)
            if n is None:
                continue
            for k in [n] + bk.leaves(n):
                used.setdefault(k, set()).add(lv)
    nodes, tracks = {}, {}

    def key(k):
        return f'{k >> 16}:{k & 0xffff}'
    # voices: event -> dialog -> text
    nvoice = 0
    for i, lv in enumerate(lvs):
        if progress:
            progress(f'Reading dialogue {i + 1}/{len(lvs)} ({lv})')
        tx = texts(levels, lv)
        for ev, dname in voices(levels, lv).items():
            n = bk.event_node(ev)
            if n is None:
                continue
            who, line = tx.get(dname, ('', ''))
            who = who.title() if who else ''
            leaves = bk.leaves(n)
            title = f'{who}: {line}' if who and line else line or dname
            info = dict(kind='voice', title=title, dialog=dname, speaker=who, text=line, level=lv)
            for j, lf in enumerate(leaves):
                if key(lf) not in nodes:
                    nodes[key(lf)] = dict(info, part=f'{j + 1}/{len(leaves)}' if len(leaves) > 1 else '')
                    nvoice += 1
            if len(leaves) > 1 and key(n) not in tracks:
                tracks[key(n)] = dict(info, parts=[key(x) for x in leaves])
    # sequences that are not dialogue: music (MPEG pieces) or chained sound effects
    for b_n in sorted(bk._b) + sorted(int(re.sub(r'\D', '', os.path.basename(f)))
                                         for f in glob.glob(os.path.join(sound_dir, 'Bnk_*.bnm'))):
        b = bk.get(b_n)
        if not b:
            continue
        for idx in range(b[1][4]):
            k = (b_n << 16) | idx
            n = bk.node(k)
            if not n or n[0] != 11 or key(k) in tracks:
                continue
            leaves = bk.leaves(k)
            if not leaves:
                continue
            lv = sorted(used.get(k, ()))
            tracks[key(k)] = dict(kind='music', title='', parts=[key(x) for x in leaves], levels=lv)
    # number the music tracks per place: "The Forest · music 2"
    per = {}
    for kk, t in sorted(tracks.items(), key=lambda kv: tuple(int(x) for x in kv[0].split(':'))):
        if t['kind'] != 'music':
            continue
        lv = t['levels']
        where = place_of(lv[0]) if lv and len({place_of(x) for x in lv}) == 1 else \
            ('Several places' if lv else f'Bank {kk.split(":")[0]} (unused?)')
        per[where] = per.get(where, 0) + 1
        t['title'] = f'{where} · track {per[where]}'
        for j, p in enumerate(t['parts']):
            if p not in nodes:
                nodes[p] = dict(kind='music', title=f"{t['title']} · part {j + 1}/{len(t['parts'])}")
    # sound designer names (.csb): group of every entry, theme names + loop points of the music tracks
    ncsb = ntheme = 0
    try:
        ent, themes = csb_match(sound_dir, progress, extra)
    except Exception as ex:                          # no .csb anywhere: the names above still work
        ent, themes = {}, []
        print('csb:', ex, file=sys.stderr)
    for k, (label, res, cands) in ent.items():
        n = nodes.setdefault(k, {})
        if label:
            n['group'], n['res'] = label, res
            ncsb += 1
            if not n.get('title'):
                n['title'] = f'{label} · {res}' if res else label
    for kk, t in tracks.items():
        if t['kind'] != 'music':
            continue
        cand = [ent.get(p, (None, None, set()))[2] for p in t['parts']]
        best = [th for th in themes if len(th[2]) == len(cand) and all(not c or x in c for x, c in zip(th[2], cand))
                and sum(1 for c in cand if c) >= max(1, len(cand) // 2)]
        if len({(b[0], b[1]) for b in best}) > 1:      # same pieces in several themes: prefer the track's place
            places = {place_of(lv) for lv in t.get('levels', [])}
            here = [b for b in best if any(b[0].replace('Music · ', '') in p for p in places)]
            best = here or best
        if best:
            label, name, _, start_loop, loop = best[0]
            names = sorted({b[1] for b in best if b[0] == label})
            name = ' / '.join(names) if len(names) <= 3 else name
            if len({b[0] for b in best}) > 1:
                label = ' / '.join(sorted({b[0].replace('Music · ', '') for b in best}))
                name = ' / '.join(sorted({b[1] for b in best}))
            t['title'] = f"{label.replace('Music · ', '')} · {name}"
            t['theme'], t['start_loop'], t['loop'] = name, start_loop, loop
            ntheme += 1
            for j, p in enumerate(t['parts']):
                if nodes.get(p, {}).get('kind') in (None, 'music'):
                    nodes.setdefault(p, {}).update(kind='music',
                                                   title=f"{t['title']} · part {j + 1}/{len(t['parts'])}")
    for k, lv in used.items():
        nodes.setdefault(key(k), {})['levels'] = sorted(lv)
    for t in tracks.values():
        t.setdefault('levels', sorted({x for p in t['parts'] for x in nodes.get(p, {}).get('levels', [])}))
    return dict(version=VERSION, nodes=nodes, tracks=tracks, voices=nvoice, csb=ncsb, themes=ntheme,
                levels={lv: level_label(lv) for lv in ['Fix'] + lvs})


def csb_match(sound_dir, progress=None, extra=()):
    """Bank entries -> .csb resources. Named entries match by (file name, size); entries named after their bank
    (Bnk_<n>.bnm: the MPEG region lost the file name) by size, which may leave several candidates.
    -> ({node key: (group label or None, resource name, {(csb, M index) candidates})},
        [(group label, theme name, [(csb, M index) per part], start loop part, loop flag)])"""
    db = csb.load(csb_files(sound_dir, extra))
    by_name, by_size = {}, {}
    for c, (label, res) in db.items():
        for i, r in res.items():
            if r.get('type') == 'sample' and r.get('file'):
                by_name.setdefault((r['file'].lower(), r.get('size')), set()).add((c, i))
                by_size.setdefault(r.get('size'), set()).add((c, i))
    ent = {}
    for f in glob.glob(os.path.join(sound_dir, 'Bnk_*.bnm')):
        n = int(re.sub(r'\D', '', os.path.basename(f)))
        for e in bnm.read_table(f):
            nm = e['name'].lower()
            cands = by_size.get(e['size'], set()) if nm.startswith('bnk_') else by_name.get((nm, e['size']), set())
            labels = {db[c][0] for c, _ in cands}
            names = {db[c][1][i]['name'] for c, i in cands}
            res = names.pop() if len(names) == 1 else '' if nm.startswith('bnk_') else os.path.splitext(e['name'])[0]
            ent[f'{n}:{e["index"]}'] = (labels.pop() if len(labels) == 1 else None, res, cands)

    def flat(c, i, depth=0):
        r = db.get(c, (None, {}))[1].get(i)
        if not r or depth > 6:
            return []
        if r.get('type') == 'sample':
            return [(c, i)]
        return [x for pc, pi in r['parts'] for x in flat(pc, pi, depth + 1)]
    themes = [(label, r['name'], flat(c, i), r.get('start_loop', 0), r.get('loop', False))
              for c, (label, res) in db.items() for i, r in res.items() if r.get('type') == 'theme']
    return ent, themes


def load(sound_dir, cache_dir, progress=None, extra=()):
    """Cached build: <cache_dir>/names_<stamp>.json."""
    st = stamp(sound_dir, extra)
    p = os.path.join(cache_dir, f'names_{st}.json')
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding='utf-8'))
            if d.get('version') == VERSION:
                return d
        except ValueError:
            pass
    d = build(sound_dir, progress, extra)
    os.makedirs(cache_dir, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False)
    return d

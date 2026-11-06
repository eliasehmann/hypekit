"""Filtered queries with facet counts and sorting for the catalog (sounds, lines, textures) and characters.

Filters are a dict; list values (or comma-separated strings) mean OR within one filter, filters combine with AND.
facets(...) counts each facet value with all *other* filters applied (so a facet never hides its own siblings).

  sounds:   q, kind, level, speaker, format, length (short|medium|long), loop (1), group, ids
  lines:    q, level, speaker, voiced (1|0), common (1 = include shared lines), ids
  textures: q, archive, format, folder, size (tiny|small|medium|large|huge), alpha (1|0), ids
  persos:   q, level, category (figure|pickup|object), ids
"""
import re

LENGTH = {'short': (0, 3), 'medium': (3, 30), 'long': (30, 1e9)}
SIZE = {'tiny': (0, 33), 'small': (33, 65), 'medium': (65, 129), 'large': (129, 257), 'huge': (257, 1 << 20)}   # longest side, half-open
SOUND_SORT = {'': 'rowid', 'title': 'title COLLATE NOCASE, rowid', 'long': 'seconds DESC, rowid', 'short': 'seconds ASC, rowid',
              'place': 'levels, rowid'}
LINE_SORT = {'': 'rowid', 'speaker': 'speaker COLLATE NOCASE, rowid', 'long': 'length(text) DESC, rowid'}
TEXTURE_SORT = {'': 'rowid', 'name': "lower(replace(path, rtrim(path, replace(path, '/', '')), '')), rowid",
                'large': 'width * height DESC, rowid', 'small': 'width * height ASC, rowid', 'folder': 'lower(path), rowid'}
PICKUP = re.compile(r'icone|diamand|herbe|potion|gold|fleche|item|bottle|fiole|plasty|noix|almanach|joyau|cle_|clef', re.I)


def vals(v):
    """'a,b' / ['a', 'b'] / 'a' / None -> ['a', 'b'] (empty strings dropped)."""
    if v is None or v == '':
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v if str(x) != '']
    return [x for x in str(v).split(',') if x != '']


def _like(q):
    return '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def _in(col, xs, p):
    p += xs
    return f"{col} IN ({','.join('?' * len(xs))})"


def _range(expr, buckets, keys, p):
    parts = []
    for k in keys:
        lo, hi = buckets[k]
        parts.append(f'({expr} >= ? AND {expr} < ?)')
        p += [lo, hi]
    return '(' + ' OR '.join(parts) + ')'


def _words(q):
    return [w for w in q.split() if w]


# ---- WHERE builders: f = filters, skip = a facet to leave out ------------------------------------------------
def sound_where(f, skip=None):
    w, p = [], []
    for word in _words(f.get('q') or ''):
        w.append("(title LIKE ? ESCAPE '\\' OR file_name LIKE ? ESCAPE '\\' OR text LIKE ? ESCAPE '\\' "
                 "OR group_name LIKE ? ESCAPE '\\' OR speaker LIKE ? ESCAPE '\\' OR id = ?)")
        p += [_like(word)] * 5 + [word]
    kinds = vals(f.get('kind'))
    if kinds and skip != 'kind':
        w.append(_in('kind', kinds, p))
    elif not kinds:
        w.append("kind != 'music part'")
    lv = vals(f.get('level'))
    if lv and skip != 'level':
        w.append('(' + ' OR '.join(['levels LIKE ?'] * len(lv)) + ')')
        p += [f'%"{x}"%' for x in lv]
    sp = vals(f.get('speaker'))
    if sp and skip != 'speaker':
        w.append(_in('speaker', sp, p))
    fm = vals(f.get('format'))
    if fm and skip != 'format':
        w.append(_in('format', fm, p))
    ln = [x for x in vals(f.get('length')) if x in LENGTH]
    if ln and skip != 'length':
        w.append(_range('seconds', LENGTH, ln, p))
    if f.get('loop') in ('1', 1, True) and skip != 'loop':
        w.append('loop = 1')
    gr = vals(f.get('group'))
    if gr and skip != 'group':
        w.append(_in('group_name', gr, p))
    ids = vals(f.get('ids'))
    if f.get('ids') is not None and skip != 'ids':
        w.append(_in('id', ids, p) if ids else '0')
    return w, p


def line_where(f, skip=None, alias=''):
    a = alias
    w, p = [], []
    for word in _words(f.get('q') or ''):
        w.append(f"({a}text LIKE ? ESCAPE '\\' OR {a}speaker LIKE ? ESCAPE '\\' OR {a}dialog LIKE ? ESCAPE '\\')")
        p += [_like(word)] * 3
    lv = vals(f.get('level'))
    if lv and skip != 'level':
        w.append(_in(f'{a}level', lv, p))
    sp = vals(f.get('speaker'))
    if sp and skip != 'speaker':
        w.append(_in(f'{a}speaker', sp, p))
    v = f.get('voiced')
    if v in ('1', '0', 1, 0) and skip != 'voiced':
        w.append(('' if str(v) == '1' else 'NOT ') + f'EXISTS (SELECT 1 FROM sound_lines j WHERE j.line_id = {a}id)')
    if f.get('common') not in ('1', 1, True):
        w.append(f'{a}common = 0')
    ids = vals(f.get('ids'))
    if f.get('ids') is not None and skip != 'ids':
        w.append(_in(f'{a}id', ids, p) if ids else '0')
    return w, p


FOLDER = "CASE WHEN instr(path, '/') THEN substr(path, 1, instr(path, '/') - 1) ELSE '' END"
MAXSIDE = 'max(width, height)'


def texture_where(f, skip=None):
    w, p = [], []
    for word in _words(f.get('q') or ''):
        w.append("(path LIKE ? ESCAPE '\\' OR id = ?)")
        p += [_like(word), word]
    ar = vals(f.get('archive'))
    if ar and skip != 'archive':
        w.append(_in('archive', ar, p))
    fm = vals(f.get('format'))
    if fm and skip != 'format':
        w.append(_in('format', fm, p))
    fo = vals(f.get('folder'))
    if fo and skip != 'folder':
        w.append(_in(FOLDER, fo, p))
    sz = [x for x in vals(f.get('size')) if x in SIZE]
    if sz and skip != 'size':
        w.append(_range(MAXSIDE, SIZE, sz, p))
    al = f.get('alpha')
    if al in ('1', '0', 1, 0) and skip != 'alpha':
        w.append(("format IN ('argb1555', 'argb4444')" if str(al) == '1' else "format NOT IN ('argb1555', 'argb4444')"))
    ids = vals(f.get('ids'))
    if f.get('ids') is not None and skip != 'ids':
        w.append(_in('id', ids, p) if ids else '0')
    return w, p


def where(w):
    return (' WHERE ' + ' AND '.join(w)) if w else ''


def page(limit, offset):
    return f' LIMIT {int(limit)} OFFSET {int(offset or 0)}' if limit else ''


# ---- runners (kit.sql = read-only query -> list of dicts) ---------------------------------------------------
def sounds(kit, f, limit=200, offset=0, sort=''):
    w, p = sound_where(f)
    items = kit.sql('SELECT * FROM sounds' + where(w) + ' ORDER BY ' + SOUND_SORT.get(sort, 'rowid') + page(limit, offset), p)
    total = kit.sql('SELECT count(*) AS n, sum(seconds) AS s FROM sounds' + where(w), p)[0]
    return dict(items=items, total=total['n'], seconds=round(total['s'] or 0, 1))


def sound_facets(kit, f):
    def grp(field, expr, frm='sounds'):
        w, p = sound_where(f, skip=field)
        return {r['v']: r['n'] for r in kit.sql(f'SELECT {expr} AS v, count(*) AS n FROM {frm}' + where(w) + ' GROUP BY v', p)
                if r['v'] not in (None, '')}
    w, p = sound_where(f, skip='level')
    lv = {r['v']: r['n'] for r in kit.sql('SELECT j.value AS v, count(*) AS n FROM sounds, json_each(sounds.levels) j'
                                          + where(w) + ' GROUP BY v', p)}
    ln = {}
    w, p = sound_where(f, skip='length')
    for k, (lo, hi) in LENGTH.items():
        ln[k] = kit.sql('SELECT count(*) AS n FROM sounds' + where(w + ['seconds >= ? AND seconds < ?']), p + [lo, hi])[0]['n']
    w, p = sound_where(f, skip='loop')
    loop = kit.sql('SELECT count(*) AS n FROM sounds' + where(w + ['loop = 1']), p)[0]['n']
    kinds = {}
    w, p = sound_where({**f, 'kind': None})
    w = [x for x in w if x != "kind != 'music part'"] + ["kind != 'music part'"]
    for r in kit.sql('SELECT kind AS v, count(*) AS n FROM sounds' + where(w) + ' GROUP BY v', p):
        kinds[r['v']] = r['n']
    return dict(kind=kinds, level=lv, speaker=grp('speaker', 'speaker'), format=grp('format', 'format'), length=ln,
                loop=loop, group=grp('group', 'group_name'))


def lines(kit, f, limit=200, offset=0, sort=''):
    w, p = line_where(f, alias='l.')
    items = kit.sql('SELECT l.*, (SELECT group_concat(j.sound_id) FROM sound_lines j WHERE j.line_id = l.id) AS sound_ids '
                    'FROM lines l' + where(w) + ' ORDER BY ' + LINE_SORT.get(sort, 'rowid').replace('rowid', 'l.rowid')
                    + page(limit, offset), p)
    for r in items:
        ids = r.pop('sound_ids', None)
        r['sounds'] = sorted(ids.split(',')) if ids else []
    total = kit.sql('SELECT count(*) AS n FROM lines l' + where(w), p)[0]['n']
    return dict(items=items, total=total)


def line_facets(kit, f):
    def grp(field, col):
        w, p = line_where(f, skip=field, alias='l.')
        return {r['v']: r['n'] for r in kit.sql(f'SELECT l.{col} AS v, count(*) AS n FROM lines l' + where(w) + ' GROUP BY v', p)
                if r['v'] not in (None, '')}
    w, p = line_where(f, skip='voiced', alias='l.')
    voiced = kit.sql('SELECT count(*) AS n FROM lines l' + where(w + ['EXISTS (SELECT 1 FROM sound_lines j WHERE j.line_id = l.id)']), p)[0]['n']
    unvoiced = kit.sql('SELECT count(*) AS n FROM lines l' + where(w + ['NOT EXISTS (SELECT 1 FROM sound_lines j WHERE j.line_id = l.id)']), p)[0]['n']
    return dict(level=grp('level', 'level'), speaker=grp('speaker', 'speaker'), voiced={'1': voiced, '0': unvoiced})


def textures(kit, f, limit=200, offset=0, sort=''):
    w, p = texture_where(f)
    items = kit.sql('SELECT * FROM textures' + where(w) + ' ORDER BY ' + TEXTURE_SORT.get(sort, 'rowid') + page(limit, offset), p)
    total = kit.sql('SELECT count(*) AS n FROM textures' + where(w), p)[0]['n']
    return dict(items=items, total=total)


def texture_facets(kit, f):
    def grp(field, expr):
        w, p = texture_where(f, skip=field)
        return {r['v']: r['n'] for r in kit.sql(f'SELECT {expr} AS v, count(*) AS n FROM textures' + where(w) + ' GROUP BY v', p)
                if r['v'] not in (None,)}
    sz = {}
    w, p = texture_where(f, skip='size')
    for k, (lo, hi) in SIZE.items():
        sz[k] = kit.sql('SELECT count(*) AS n FROM textures' + where(w + [f'{MAXSIDE} >= ? AND {MAXSIDE} < ?']), p + [lo, hi])[0]['n']
    w, p = texture_where(f, skip='alpha')
    alpha = kit.sql('SELECT count(*) AS n FROM textures' + where(w + ["format IN ('argb1555', 'argb4444')"]), p)[0]['n']
    return dict(archive=grp('archive', 'archive'), format=grp('format', 'format'),
                folder={(k or '(top)'): v for k, v in grp('folder', FOLDER).items()}, size=sz, alpha=alpha)


# ---- characters (records in memory) ---------------------------------------------------------------------------
def category(r):
    if r['parts'] >= 150:
        return 'figure'
    return 'pickup' if PICKUP.search(r['name']) else 'object'


def persos(recs, f, sort=''):
    """-> dict(items=[group per name: {name, parts, states, category, places: [{id, level}]}], total, facets)."""
    words = [w.lower() for w in _words(f.get('q') or '')]
    lv, cat, ids = vals(f.get('level')), vals(f.get('category')), f.get('ids')
    idset = set(vals(ids)) if ids is not None else None

    def ok(r, skip=None):
        if any(w not in r['name'].lower() for w in words):
            return False
        if lv and skip != 'level' and r['level'] not in lv:
            return False
        if cat and skip != 'category' and category(r) not in cat:
            return False
        return idset is None or r['id'] in idset or r['name'] in idset
    named = [r for r in recs if r['name']]
    groups = {}
    for r in named:
        if ok(r):
            g = groups.setdefault(r['name'], dict(name=r['name'], parts=r['parts'], states=r['states'], category=category(r),
                                                  places=[]))
            g['places'].append(dict(id=r['id'], level=r['level']))
    items = list(groups.values())
    key = {'az': lambda g: g['name'].lower(), 'moves': lambda g: (-g['states'], g['name'].lower()),
           'places': lambda g: (-len(g['places']), g['name'].lower())}.get(sort, lambda g: (-g['parts'], -g['states'], g['name'].lower()))
    items.sort(key=key)
    fc_lv, fc_cat = {}, {}
    for r in named:
        if ok(r, 'level'):
            fc_lv[r['level']] = fc_lv.get(r['level'], 0) + 1
        if ok(r, 'category'):
            fc_cat.setdefault(category(r), set()).add(r['name'])
    return dict(items=items, total=len(items), facets=dict(level=fc_lv, category={k: len(v) for k, v in fc_cat.items()}))

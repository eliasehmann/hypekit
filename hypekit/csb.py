"""Ubi Sound Studio .csb sound scripts (disc: Sound\\*.csb and Sound\\<Language>\\V_*.csb; text, CPA editor format).

The sound designers' project files: one per group (P_Hype = Hype, PA_Loups = wolves, PB_Rajoth = boss, M_<place> =
music, V_<level> = voices). The game itself plays the compiled .bnm banks; the .csb give the names and groups.
Blocks:  {SndResourceE:n(file^SndResourceM:n)  SetName(<name>)  SetComment(...)}
         {SndResourceM:n {SndResourceDisk:n(TYPE_SAMPLE|THEME|RANDOM|SWITCH) SetFileName("x.apm") SetDataSize(n)
                          SetLoop[ab](..) SetStartLoop(n) ...} {SndThemePartListM: {SndThemePartM:i LoadResource(f^SndResourceM:m)}}}
         {SndEventE:n(...) SetName(Play_x) SetParam1(f^SndResourceE:m)}
The installed game has no .csb: they are on the disc (pass disc folders as extra sound sources).
"""
import glob
import os
import re

# group label of each .csb (file names are French): None = use the name after the prefix
GROUPS = {
    'p_animaux': 'Animals', 'p_common': 'Common', 'p_hype': 'Hype', 'p_magie': 'Magic', 'p_objets': 'Objects',
    'p_pasgen': 'Footsteps', 'pas_hype': 'Hype · footsteps', 'pa_chauvesouris': 'Bats', 'pa_dragons': 'Dragons',
    'pa_loups': 'Wolves', 'pa_sanglier': 'Boar', 'pb_barnack': 'Barnak', 'pb_dragoncasino': 'Casino dragon',
    'pb_ernost-robot': 'Ernost robot', 'pb_gladiateur': 'Gladiator', 'pb_granslack': 'Granslack',
    'pb_moinesumo': 'Sumo monk', 'pb_rajoth': 'Rajoth', 'pb_senekal': 'Senekal', 'pe_armure': 'Armour',
    'pe_fantomes': 'Ghosts', 'pe_gardes': 'Guards', 'pe_squelettes': 'Skeletons', 'pe_tapisseries': 'Tapestries',
    's_dummyambiance': 'Ambience', 's_dummyia': 'Scripted sounds', 's_sonsmagiques': 'Magic effects',
    'sp_sonsponctuels': 'One-shot sounds', 'themes': 'Themes',
    'm_astrolabe': 'Astrolabe', 'm_bigboss': 'Final boss', 'm_cachots': 'Dungeons', 'm_casino': 'Field of Courage',
    'm_ciel': 'Sky', 'm_citeperdue': 'Lost City', 'm_foretbrigands': 'Forest', 'm_forteresse': 'Fortress',
    'm_generique': 'Credits', 'm_intro_conclusion': 'Intro + ending', 'm_laboratoire': 'Laboratories',
    'm_manoirgogood': "Gogoud's Manor", 'm_menu': 'Menu', 'm_monastere': 'Monastery', 'm_toptower': 'Top of the tower',
    'm_toras': 'Torras', 'm_tournoire': 'Black Tower', 'm_ville': 'Brigand Village'}


def group_label(csb):
    k = os.path.splitext(os.path.basename(csb))[0].lower()
    if k in GROUPS:
        lab = GROUPS[k]
    else:
        lab = k.split('_', 1)[-1].capitalize()
    if k.startswith('m_'):
        return f'Music · {lab}'
    if k.startswith('v_'):
        return f'Voices · {lab}'
    return lab


RES_E = re.compile(r'^\{SndResourceE:(\d+)\(([^^]+)\^SndResourceM:(\d+)\)')
RES_M = re.compile(r'^\{SndResourceM:(\d+)')
DISK = re.compile(r'\{SndResourceDisk:\d+\((TYPE_\w+)\)')
SET = re.compile(r'^(SetName|SetFileName|SetDataSize|SetStartLoop|SetLoop\[ab\]|SetComment|SetVolume)\((.*)\)\s*$')
LOAD = re.compile(r'LoadResource\(([^^]+)\^SndResourceM:(\d+)\)')


def parse(path):
    """-> {M index: dict(type, name, file, size, loop, start_loop, parts=[(csb, M index)], comment)}"""
    me = os.path.basename(path).lower()
    res, cur, names = {}, None, {}
    pending_name = None
    for raw in open(path, encoding='latin-1', errors='replace'):
        line = raw.strip()
        m = RES_E.match(line)
        if m:
            pending_name, cur = int(m.group(3)), None
            continue
        m = RES_M.match(line)
        if m:
            cur, pending_name = res.setdefault(int(m.group(1)), dict(parts=[])), None
            continue
        if line.startswith('{SndEvent') or line.startswith('{CsbHeader'):
            cur = pending_name = None
            continue
        m = SET.match(line)
        if m and pending_name is not None and m.group(1) in ('SetName', 'SetComment'):
            names.setdefault(pending_name, {})[m.group(1)] = m.group(2).strip('"')
            continue
        if cur is None:
            continue
        m = DISK.search(line)
        if m:
            cur['type'] = m.group(1)[5:].lower()
            continue
        m = LOAD.search(line)
        if m:
            cur['parts'].append((m.group(1).lower(), int(m.group(2))))
            continue
        if m := SET.match(line):
            k, v = m.group(1), m.group(2).strip('"')
            if k == 'SetFileName':
                cur['file'] = v
            elif k == 'SetDataSize':
                cur['size'] = int(v)
            elif k == 'SetStartLoop':
                cur['start_loop'] = int(v)
            elif k.startswith('SetLoop'):
                cur['loop'] = v.upper() == 'TRUE'
    for i, r in res.items():
        n = names.get(i, {})
        r['name'] = n.get('SetName', '')
        r['comment'] = n.get('SetComment', '')
    return me, res


def find(folders):
    """All .csb under <folder>\\Sound (+ language subfolders) of each folder, first copy of a file name wins."""
    seen = {}
    for d in folders:
        for f in sorted(glob.glob(os.path.join(d, 'Sound', '*.csb')) + glob.glob(os.path.join(d, 'Sound', '*', '*.csb'))):
            seen.setdefault(os.path.basename(f).lower(), f)
    return list(seen.values())


def default_folders(install_root, extra=()):
    """The opened install first, then extra folders (disc copies: the .csb are not installed)."""
    return [install_root] + list(extra)


def load(paths):
    """-> {csb file lower: (label, {M index: resource})}"""
    out = {}
    for p in paths:
        me, res = parse(p)
        out[me] = (group_label(p), res)
    return out

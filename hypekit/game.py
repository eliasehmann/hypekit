"""Finding and opening a Hype install, cross-platform.

A game folder is any folder with Gamedata/World/Sound and Gamedata/World/Levels (an installed game; Windows, Wine
or a copy). File names in Hype differ in case between folders, so lookups are case-insensitive (Linux/macOS).
"""
import glob
import os
import sys

ENV_GAME = 'HYPEKIT_GAME'          # game folder
ENV_DISCS = 'HYPEKIT_DISCS'        # os.pathsep-separated disc copies (they hold the .csb sound names)
ENV_CACHE = 'HYPEKIT_CACHE'        # cache folder (catalog, decoded files)


def ci_path(base, *parts):
    """base/parts with each part matched case-insensitively; None if missing."""
    p = base
    for part in parts:
        q = os.path.join(p, part)
        if os.path.exists(q):
            p = q
            continue
        try:
            low = part.lower()
            hit = next((n for n in os.listdir(p) if n.lower() == low), None)
        except OSError:
            return None
        if hit is None:
            return None
        p = os.path.join(p, hit)
    return p


def is_game(folder):
    return bool(folder and ci_path(folder, 'Gamedata', 'World', 'Sound') and ci_path(folder, 'Gamedata', 'World', 'Levels'))


def _ubi_ini_dirs():
    """Directory= lines of Ubi.ini (written by the Windows installer; also the VirtualStore copy)."""
    out = []
    win = os.environ.get('WINDIR', r'C:\Windows')
    cands = [os.path.join(win, 'UbiSoft', 'Ubi.ini')]
    if os.environ.get('LOCALAPPDATA'):
        cands.append(os.path.join(os.environ['LOCALAPPDATA'], 'VirtualStore', 'Windows', 'UbiSoft', 'Ubi.ini'))
    for f in cands:
        try:
            for line in open(f, encoding='latin-1'):
                if line.lower().startswith('directory='):
                    out.append(line.split('=', 1)[1].strip())
        except OSError:
            pass
    return out


def candidates():
    """Likely game folders, best first (not checked)."""
    c = []
    if os.environ.get(ENV_GAME):
        c.append(os.environ[ENV_GAME])
    if sys.platform == 'win32':
        c += _ubi_ini_dirs()
        for pf in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), r'C:\Games'):
            if pf:
                c += glob.glob(os.path.join(pf, 'Hype*'))
    else:
        home = os.path.expanduser('~')
        for prefix in [os.path.join(home, '.wine')] + glob.glob(os.path.join(home, '.local', 'share', 'Steam',
                                                                               'steamapps', 'compatdata', '*', 'pfx')):
            c += glob.glob(os.path.join(prefix, 'drive_c', 'Program Files*', 'Hype*'))
            c += glob.glob(os.path.join(prefix, 'drive_c', 'Games', 'Hype*'))
    seen, out = set(), []
    for p in c:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def find_game():
    """First candidate that is a game folder, or None."""
    return next((p for p in candidates() if is_game(p)), None)


def find_discs():
    """Disc copies to read .csb names from ($HYPEKIT_DISCS)."""
    env = os.environ.get(ENV_DISCS)
    if env:
        return [p for p in env.split(os.pathsep) if os.path.isdir(p)]
    return []


def cache_root():
    """Per-user cache folder: $HYPEKIT_CACHE, %LOCALAPPDATA%/hypekit, ~/Library/Caches/hypekit or ~/.cache/hypekit."""
    if os.environ.get(ENV_CACHE):
        return os.environ[ENV_CACHE]
    ws = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if os.path.isdir(os.path.join(ws, 'work')) and os.path.isdir(os.path.join(ws, 'sources')):
        # development checkout inside the workspace: generated output goes to work/. (Also avoids Microsoft Store
        # Python, which redirects AppData writes into its package folder where vgmstream-cli cannot see them.)
        return os.path.join(ws, 'work', 'hypekit')
    if sys.platform == 'win32' and os.environ.get('LOCALAPPDATA'):
        return os.path.join(os.environ['LOCALAPPDATA'], 'hypekit')
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Caches/hypekit')
    return os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'hypekit')


class Game:
    """Paths of one install."""

    def __init__(self, folder):
        if not is_game(folder):
            raise FileNotFoundError(f'not a Hype game folder (no Gamedata/World/Sound + Levels): {folder}')
        self.root = os.path.abspath(folder)
        self.gamedata = ci_path(self.root, 'Gamedata')
        self.sound = ci_path(self.gamedata, 'World', 'Sound')
        self.levels = ci_path(self.gamedata, 'World', 'Levels')

    def level_names(self):
        """Level folders that hold a <level>.lng, sorted."""
        out = []
        for d in sorted(os.listdir(self.levels), key=str.lower):
            if os.path.isdir(os.path.join(self.levels, d)) and ci_path(self.levels, d, d + '.lng'):
                out.append(d)
        return out

    def lng(self, level):
        """<level>.lng path (level 'Fix' = Levels/Fix.lng), None if missing."""
        if level.lower() == 'fix':
            return ci_path(self.levels, 'Fix.lng')
        return ci_path(self.levels, level, level + '.lng')

    def ci_level_file(self, *parts):
        """A file under Gamedata/World/Levels (case-insensitive), None if missing."""
        return ci_path(self.levels, *parts)

    def model_levels(self):
        """Level folders that hold <level>.sna + .rtb (3D data), sorted."""
        return [d for d in sorted(os.listdir(self.levels), key=str.lower)
                if os.path.isdir(os.path.join(self.levels, d)) and ci_path(self.levels, d, d + '.sna')
                and ci_path(self.levels, d, d + '.rtb')]

    def archives(self):
        """Texture archives: {'Textures': path, 'Vignette': path} (those present)."""
        out = {}
        for n in ('Textures', 'Vignette'):
            p = ci_path(self.gamedata, n + '.cnt')
            if p:
                out[n] = p
        return out

    def __repr__(self):
        return f'<Game {self.root}>'

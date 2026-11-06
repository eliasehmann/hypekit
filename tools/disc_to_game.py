"""Make an installed-layout copy of an extracted disc for one language, so hypekit can read it:

    python tools/disc_to_game.py <disc folder> <out folder> [--lang English]

On the disc, the language's voice banks are in Gamedata/World/Sound/<Language>/ and its text/sound tables in
LangData/<Language>/world/levels/<level>/; the installer merges them into Gamedata/World/Sound and .../Levels.
This does the same by copying (the disc folder stays untouched). Videos are left out. Prints a short summary.
"""
import argparse
import os
import shutil
import sys


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('disc')
    ap.add_argument('out')
    ap.add_argument('--lang', help='LangData subfolder (default: the only one on the disc)')
    a = ap.parse_args(argv)
    gd = os.path.join(a.disc, 'Gamedata')
    langs = sorted(os.listdir(os.path.join(a.disc, 'LangData'))) if os.path.isdir(os.path.join(a.disc, 'LangData')) else []
    lang = a.lang or (langs[0] if len(langs) == 1 else None)
    if not os.path.isdir(gd) or not lang:
        sys.exit(f'need <disc>/Gamedata and one LangData language (found {langs})')
    out_gd = os.path.join(a.out, 'Gamedata')
    n = 0
    # 1. Gamedata without the videos and without the other languages' sound folders
    for root, dirs, files in os.walk(gd):
        rel = os.path.relpath(root, gd)
        if rel == '.':
            dirs[:] = [d for d in dirs if d.lower() != 'videos']
        if os.path.normcase(rel) == os.path.normcase(os.path.join('World', 'Sound')):
            dirs[:] = []                                   # language subfolders: merged below
        os.makedirs(os.path.join(out_gd, rel), exist_ok=True)
        for f in files:
            dst = os.path.join(out_gd, rel, f)
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(os.path.join(root, f)):
                shutil.copy2(os.path.join(root, f), dst)
            n += 1
    # 2. the language's voice banks into Sound/
    snd = os.path.join(gd, 'World', 'Sound', lang)
    m = 0
    if os.path.isdir(snd):
        for f in os.listdir(snd):
            shutil.copy2(os.path.join(snd, f), os.path.join(out_gd, 'World', 'Sound', f))
            m += 1
    # 3. the language's level files into Levels/<level>/ (and Fix.* into Levels/)
    lv = os.path.join(a.disc, 'LangData', lang, 'world', 'levels')
    k = 0
    for root, dirs, files in os.walk(lv):
        rel = os.path.relpath(root, lv)
        dst_dir = os.path.join(out_gd, 'World', 'Levels', rel)
        os.makedirs(dst_dir, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(dst_dir, f))
            k += 1
    print(f'{lang}: {n} game files, {m} voice banks, {k} level text/sound files -> {os.path.abspath(a.out)}')


if __name__ == '__main__':
    main()

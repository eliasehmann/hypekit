"""Dialogue text from the .lng files (SNA archives), in the install's language.

The text is stored in the code page of the release: Windows-1252 for the Western ones, Windows-1250 for the Polish
one. `install_encoding` tells them apart (or takes $HYPEKIT_ENCODING).

Each level's text block holds dialog sequences in order: a sequence name (`rajoth2_sequence1`), a speaker tag
(`RAJOTH :`), wrapped text fragments, then the next sequence. Fragments are joined into one line per speaker turn.
Lines that occur in more than two levels are pickup messages / menu text ("common").
"""
import codecs
import functools
import os
import re
from dataclasses import dataclass, asdict

from . import sna
from .game import ci_path

DEFAULT = 'cp1252'                 # Western releases (English, French, German, Spanish, Italian, ...)
ENV_ENCODING = 'HYPEKIT_ENCODING'  # overrides the detection, e.g. cp1250
# Letters a code page adds for its language. They don't count as "high bytes" in the junk filter, so short words
# made mostly of them ('źródło') survive. cp1252 has no entry on purpose: its filters stay exactly as they were.
ALPHABET = {'cp1250': 'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ'}

STR = re.compile(rb'[\x20-\x7e\x80-\xff]{3,}')
SEQ = re.compile(r'^[A-Za-z0-9_]+$')          # sequence / label names: no spaces, no punctuation
# detection: 0xB3 / 0xB9 are 'ł' / 'ą' in Windows-1250 and '³' / '¹' in Windows-1252, where they never touch a letter
POLISH = re.compile(rb'[A-Za-z][\xb3\xb9]|[\xb3\xb9][a-z]')
DETECT_FILES = 4                   # Fix.lng + the first levels are enough to tell


@functools.lru_cache(maxsize=None)
def _rules(encoding):
    """(TEXTY, SPEAKER, alphabet) for a code page. The 'high' class is what bytes 0xA0-0xFF decode to, plus the
    letters of 0x80-0x9F (cp1250: Ś Ź ś ź ...). For cp1252 it is \x80-\xff, as before."""
    if encoding == DEFAULT:
        high = r'\x80-\xff'
    else:
        chars = bytes(range(0xa0, 0x100)).decode(encoding, 'ignore')
        chars += ''.join(c for c in bytes(range(0x80, 0xa0)).decode(encoding, 'ignore') if c.isalpha())
        high = ''.join(re.escape(c) for c in chars)
    texty = re.compile(r"^[A-Za-z0-9 ,.'\"!?:;()\-_/%&+*=\[\]" + high + r"]+$")
    speaker = re.compile(r"^[A-Z0-9 \-'" + high + r"]{2,}\s?:$")
    return texty, speaker, frozenset(ALPHABET.get(encoding, ''))


def normalize(encoding):
    """Canonical codec name ('windows-1250' -> 'cp1250'); ValueError if Python doesn't know it."""
    try:
        return codecs.lookup(encoding).name
    except LookupError:
        raise ValueError(f'unknown text encoding: {encoding}') from None


def scan(data, encoding=DEFAULT):
    """Ordered list of (kind, text) found in one block of bytes: kind is 'seq', 'who' or 'txt'."""
    texty, speaker, alphabet = _rules(encoding)
    out = []
    for mo in STR.finditer(data):
        try:
            s = mo.group().decode(encoding)
        except UnicodeDecodeError:
            continue
        if not texty.match(s) or not (re.search('[A-Za-z]', s) or alphabet & set(s)):
            continue
        if sum(ch > '\x7e' and ch not in alphabet for ch in s) > max(1, len(s) // 5):
            # pointer bytes that happen to be printable
            # (proportional: real French/Spanish/German lines have several accents, pointers are mostly high bytes)
            continue
        if speaker.match(s):
            out.append(('who', s.rstrip(' :').strip()))
        elif SEQ.match(s) and (('_' in s) or re.search(r'\d', s)):
            out.append(('seq', s))              # sequence / label names
        elif len(s) <= 4 and ' ' not in s:
            continue                            # 4-byte floats that happen to be printable
        elif max(sum(c.isalpha() for c in w) for w in s.split()) < 2:
            continue                            # 'X ñ', '¡a ¢a': pointer bytes, no word with 2+ letters
        else:
            out.append(('txt', s + ('' if s.endswith(' ') else ' ')))   # highlighted words are separate strings
    return out


def fragments(path, encoding=DEFAULT):
    """Ordered list of (kind, text) for one .lng: kind is 'seq', 'who' or 'txt'."""
    out = []
    for m, b, base, data in sna.read_sna(path):
        if data:
            out += scan(data, encoding)
    return out


def detect(blocks):
    """Code page of an install's text from its raw .lng blocks: 'cp1250' for the Polish release, else 'cp1252'.

    Looks only at strings that read like sentences (12+ bytes, a space, mostly ASCII letters) and counts those with
    'ł' / 'ą' next to a letter. Polish has them in most sentences, Western text in none."""
    total = hits = 0
    for data in blocks:
        for mo in STR.finditer(data):
            b = mo.group()
            if len(b) < 12 or b' ' not in b or sum(c > 0x7e for c in b) > len(b) // 5 \
                    or sum(chr(c).isalpha() for c in b if c < 0x7f) < 8:
                continue
            total += 1
            hits += bool(POLISH.search(b))
    return 'cp1250' if hits >= 5 and hits * 10 >= total else DEFAULT


@functools.lru_cache(maxsize=None)
def _detect_install(levels):
    files = [ci_path(levels, 'Fix.lng')]
    try:
        files += [ci_path(levels, d, d + '.lng') for d in sorted(os.listdir(levels), key=str.lower)
                  if os.path.isdir(os.path.join(levels, d))]
    except OSError:
        pass

    def blocks():
        for f in [f for f in files if f][:DETECT_FILES]:
            try:
                for m, b, base, data in sna.read_sna(f):
                    if data:
                        yield data
            except (OSError, ValueError, IndexError):
                continue
    return detect(blocks())


def install_encoding(levels):
    """Code page of the text in a Gamedata/World/Levels folder: $HYPEKIT_ENCODING if set, else detected (cached)."""
    env = os.environ.get(ENV_ENCODING)
    if env:
        return normalize(env)
    return _detect_install(os.path.abspath(levels))


def turns(frags):
    """Join fragments into (seq, speaker, line) turns."""
    res, seq, who, buf = [], '', '', []

    def flush():
        if buf:
            line = re.sub(r'\s+', ' ', ''.join(buf)).strip()
            if line:
                res.append((seq, who, line))
        buf.clear()

    for kind, s in frags:
        if kind == 'seq':
            flush()
            if s.split('_')[0].lower() != seq.split('_')[0].lower():
                who = ''                            # new speaker group (rajoth2_sequence1..5 share one tag)
            seq = s
        elif kind == 'who':
            flush()
            who = s
        else:
            buf.append(s)
    flush()
    return res


@dataclass
class Line:
    """One speaker turn. id = '<level>:<n>' (n = order in the level)."""
    id: str
    level: str
    n: int
    dialog: str          # sequence name, links to voice sounds (Sound.dialog)
    speaker: str         # as written in the game ('RAJOTH'), '' for narration / labels
    text: str
    common: bool = False  # occurs in more than two levels (pickup / menu text)

    def to_dict(self):
        return asdict(self)


def read_levels(game):
    """{level: [Line]} for every level + 'Fix'."""
    per = {}
    enc = install_encoding(game.levels)
    for lv in ['Fix'] + game.level_names():
        p = game.lng(lv)
        if not p:
            continue
        per[lv] = [Line(f'{lv}:{i}', lv, i, seq, who, line)
                   for i, (seq, who, line) in enumerate(turns(fragments(p, enc)))]
    count = {}
    for lines in per.values():
        for t in {x.text for x in lines}:
            count[t] = count.get(t, 0) + 1
    for lines in per.values():
        for x in lines:
            x.common = count[x.text] > 2
    return per

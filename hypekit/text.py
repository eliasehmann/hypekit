"""Dialogue text from the .lng files (SNA archives), in the install's language.

Each level's text block holds dialog sequences in order: a sequence name (`rajoth2_sequence1`), a speaker tag
(`RAJOTH :`), wrapped text fragments, then the next sequence. Fragments are joined into one line per speaker turn.
Lines that occur in more than two levels are pickup messages / menu text ("common").
"""
import re
from dataclasses import dataclass, asdict

from . import sna

STR = re.compile(rb'[\x20-\x7e\x80-\xff]{3,}')
TEXTY = re.compile(r"^[A-Za-z0-9 ,.'\"!?:;()\-_/%&+*=\[\]\x80-\xff]+$")
SEQ = re.compile(r'^[A-Za-z0-9_]+$')          # sequence / label names: no spaces, no punctuation
SPEAKER = re.compile(r'^[A-Z0-9 \-\'\x80-\xff]{2,}\s?:$')


def fragments(path):
    """Ordered list of (kind, text) for one .lng: kind is 'seq', 'who' or 'txt'."""
    out = []
    for m, b, base, data in sna.read_sna(path):
        if not data:
            continue
        for mo in STR.finditer(data):
            try:
                s = mo.group().decode('cp1252')
            except UnicodeDecodeError:
                continue
            if not TEXTY.match(s) or not re.search('[A-Za-z]', s):
                continue
            if sum(ch > '\x7e' for ch in s) > max(1, len(s) // 5):   # pointer bytes that happen to be printable
                # (proportional: real French/Spanish/German lines have several accents, pointers are mostly high bytes)
                continue
            if SPEAKER.match(s):
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
    for lv in ['Fix'] + game.level_names():
        p = game.lng(lv)
        if not p:
            continue
        per[lv] = [Line(f'{lv}:{i}', lv, i, seq, who, line)
                   for i, (seq, who, line) in enumerate(turns(fragments(p)))]
    count = {}
    for lines in per.values():
        for t in {x.text for x in lines}:
            count[t] = count.get(t, 0) + 1
    for lines in per.values():
        for x in lines:
            x.common = count[x.text] > 2
    return per

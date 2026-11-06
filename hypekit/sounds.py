"""Sounds: every sound of an install as Python objects, with names, tracks and decoding. No UI code.

    lib = Library(sound_dir, cache_dir).load()
    for s in lib.search('ragoth', kind='voice'):
        print(s.title, s.seconds)
        lib.export(s, 'out.wav')                      # or: ch, rate, samples = lib.decode(s)

Layers: bnm (bank format, PCM/APM decode) -> soundnames + csb (names, tracks, owners, levels)
-> this module (Sound objects, decoding incl. Ubi MPEG via vgmstream, joining tracks).
Ubi MPEG: the first decode of a bank runs vgmstream-cli on the whole bank into <cache>/vgm/<bank>_<size>_<mtime>/.
vgmstream-cli is found via the vgmstream argument, $HYPEKIT_VGMSTREAM or PATH; without it MPEG raises NotAvailable.
"""
import array
import collections
import glob
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import wave

from . import bnm as B
from . import soundnames as N

VGM_NAME = re.compile(r'^(\d+)_bnm_(\d+)_\d+-[0-9a-f]{8}_.*\.wav$', re.I)     # ?s_?n.wav, group 2 = node index

FORMAT = {'pcm': 'PCM', 'apm': 'APM', 'mpd': 'MPEG', 'stream': 'APM stream', 'seq': 'Track'}
KINDS = (('voice', 'Dialogue'), ('music', 'Music'), ('sfx', 'Sound effects'), ('ambience', 'Ambience'),
         ('unused', 'Unused'))
STREAMS = 'Streams (.apm)'
CACHE_MAX = 12                     # decoded sounds kept in memory


class NotAvailable(Exception):
    """The sound cannot be decoded here (vgmstream missing, entry outside the bank...)."""


class Sound:
    """One playable item: a bank entry, a standalone .apm file or a track (sequence of entries).
    kind: voice | music (a track) | music part | sfx | ambience | unused.  seconds: None until known (MPEG)."""
    __slots__ = ('uid', 'bank', 'id', 'index', 'name', 'codec', 'rate', 'channels', 'size', 'volume', 'loop',
                 'external', 'file', 'data', 'seconds', 'title', 'kind', 'levels', 'text', 'parts', 'part',
                 'start_loop', 'group', 'dialog', 'speaker')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))
        self.levels = self.levels or []
        self.parts = self.parts or []
        self.start_loop = self.start_loop or 0

    @property
    def key(self):
        return f'{self.bank}:{self.index}:{self.codec}'

    @property
    def format(self):
        return FORMAT[self.codec]

    @property
    def stem(self):
        return f'{len(self.parts)} parts' if self.codec == 'seq' else os.path.splitext(self.name)[0]

    def loop_start(self):
        """Seconds where a looping theme jumps back to (.csb SetStartLoop, 0-based part), None if unknown."""
        if not self.start_loop:
            return 0.0
        head = self.parts[:self.start_loop]
        return sum(p.seconds for p in head) if all(p.seconds for p in head) else None

    def file_name(self):
        """Export name: <bank>_<index>_<code> - <readable title>.wav"""
        t = re.sub(r'[^\w\- ]+', '', self.title or '').strip()[:50].strip()
        base = f'{self.bank}_{self.index}_{"track" if self.codec == "seq" else self.stem}'
        return f'{base} - {t}.wav' if t and t != self.stem else f'{base}.wav'

    def __repr__(self):
        return f'<Sound {self.uid} {self.key} {self.title!r}>'


class Library:
    """All sounds of one Sound folder (or one .bnm / .apm file): names, tracks, decoding."""

    def __init__(self, path, cache_dir, vgmstream=None, extra=()):
        self.path = os.path.abspath(path)
        self.cache_dir = cache_dir
        self.vgmstream = find_vgmstream(vgmstream)
        self.extra = list(extra)                      # more folders with Sound/*.csb (disc copies)
        self.folder = self.path if os.path.isdir(self.path) else os.path.dirname(self.path)
        self.banks = collections.OrderedDict()        # bank name -> [Sound] (entries, then the bank's tracks)
        self.list = []                                # every Sound, index = uid
        self.apm = {}                                 # lower file name -> path (standalone streams)
        self.level_names = {}                         # level -> 'The Forest (brigand2)'
        self.errors = []
        self._vgm = {}                                # bank file -> {node index: wav path}
        self._vgm_meta = {}                           # bank file -> {node index: seconds}
        self._vgm_lock = threading.Lock()
        self._cache = collections.OrderedDict()
        self._cache_lock = threading.Lock()

    # ---- loading -------------------------------------------------------------------------------------------
    def load(self, progress=None):
        for f in glob.glob(os.path.join(self.folder, '*.apm')):
            self.apm[os.path.basename(f).lower()] = f
        if os.path.isdir(self.path):
            banks = sorted(glob.glob(os.path.join(self.path, '*.bnm')), key=_num)
            streams = sorted(self.apm.values(), key=str.lower)
        elif self.path.lower().endswith('.bnm'):
            banks, streams = [self.path], []
        else:
            banks, streams = [], [self.path]
        for i, f in enumerate(banks):
            name = os.path.splitext(os.path.basename(f))[0]
            try:
                es = B.read_table(f)
            except Exception as ex:
                self.errors.append(f'{name}: {ex}')
                continue
            with open(f, 'rb') as fh:
                self.banks[name] = [self._entry(name, f, fh, e) for e in es]
            if progress and i % 20 == 0:
                progress(f'Reading banks {i + 1}/{len(banks)}')
        if streams:
            lst = []
            for f in streams:
                try:
                    lst.append(self._stream(f))
                except Exception as ex:
                    self.errors.append(f'{os.path.basename(f)}: {ex}')
            self.banks[STREAMS] = lst
        try:
            self._names(N.load(self.folder, os.path.join(self.cache_dir, 'names'), progress, self.extra))
        except Exception as ex:                       # names are a bonus: everything else works without them
            self.errors.append(f'names: {ex}')
            for s in self._all():
                s.title = s.title or s.stem
                s.kind = s.kind or 'sfx'
        self.list = list(self._all())
        for i, s in enumerate(self.list):
            s.uid = i
        return self

    def _all(self):
        return (s for v in self.banks.values() for s in v)

    def _names(self, d):
        self.level_names = d.get('levels', {})
        by = {}
        for bank, lst in self.banks.items():
            for s in lst:
                if s.codec == 'stream':
                    s.kind, s.title = 'ambience', s.stem
                    continue
                by[f'{bank[4:]}:{s.index}'] = s
                n = d['nodes'].get(f'{bank[4:]}:{s.index}', {})
                s.levels = n.get('levels', [])
                s.kind = n.get('kind') or ('sfx' if s.levels else 'unused')
                s.text = n.get('text') or ''
                s.part = n.get('part') or ''
                s.group = n.get('group') or ''
                s.dialog = n.get('dialog') or ''
                s.speaker = n.get('speaker') or ''
                s.title = n.get('title') or s.stem
                if s.kind == 'voice' and s.part:
                    s.title += f'  (part {s.part})'
        for k, t in d['tracks'].items():
            parts = [by[p] for p in t['parts'] if p in by]
            bank = f'Bnk_{k.split(":")[0]}'
            if not parts or bank not in self.banks:
                continue
            secs = None if any(p.seconds is None for p in parts) else sum(p.seconds for p in parts)
            idx = int(k.split(':')[1])
            self.banks[bank].append(Sound(
                bank=bank, id=idx, index=idx, name=f'{len(parts)} parts', codec='seq', rate=parts[0].rate,
                channels=max(p.channels for p in parts), size=sum(p.size for p in parts), volume=parts[0].volume,
                loop=int(bool(t.get('loop'))), external=False, file=parts[0].file, seconds=secs, title=t['title'],
                kind=t['kind'], levels=t['levels'], text=t.get('text', ''), parts=parts,
                start_loop=t.get('start_loop') or 0, group=t.get('title', '').split(' · ')[0],
                dialog=t.get('dialog', ''), speaker=t.get('speaker', '')))
            for p in parts:
                if t['kind'] == 'music' and p.kind != 'voice':
                    p.kind = 'music part'

    def _entry(self, bank, path, fh, e):
        s = Sound(bank=bank, file=path, **{k: e[k] for k in ('id', 'index', 'name', 'codec', 'rate', 'channels',
                                                              'size', 'volume', 'loop', 'external', 'data')})
        if s.codec == 'pcm':
            s.seconds = s.size / (2 * s.channels * s.rate)
        elif s.codec == 'apm' and not s.external:
            fh.seek(s.data)                           # the embedded .apm header has the real channels/rate
            tag, ch, rate = struct.unpack('<HHI', fh.read(8))
            if tag == 0x2000 and ch in (1, 2) and rate:
                s.channels, s.rate = ch, rate
            s.seconds = max(0, s.size - 0x64) * 2 / s.channels / s.rate
        elif s.external and s.name.lower() in self.apm:
            s.seconds = _apm_seconds(self.apm[s.name.lower()])
        else:                                         # MPEG: known once vgmstream decoded the bank
            self._mpeg_seconds(s)
        return s

    def _stream(self, f):
        with open(f, 'rb') as fh:
            hd = fh.read(0x64)
        tag, ch, rate = struct.unpack_from('<HHI', hd, 0)
        if tag != 0x2000 or hd[0x14:0x18] != b'vs12':
            raise ValueError('not an APM file')
        return Sound(bank=STREAMS, id=0, index=os.path.basename(f), name=os.path.basename(f), codec='stream',
                     rate=rate, channels=ch, size=os.path.getsize(f), volume=100, loop=0, external=False, file=f,
                     data=None, seconds=_apm_seconds(f))

    # ---- queries -------------------------------------------------------------------------------------------
    def __len__(self):
        return len(self.list)

    def __iter__(self):
        return iter(self.list)

    def get(self, uid):
        return self.list[uid] if 0 <= uid < len(self.list) else None

    def search(self, query='', kind=None, level=None, group=None, parts=False):
        """Sounds whose title / file / text / bank / levels contain query (case-insensitive)."""
        q = (query or '').lower()
        for s in self.list:
            if s.kind == 'music part' and not parts:
                continue
            if kind and s.kind != kind or level and level not in s.levels or group and s.group != group:
                continue
            if q and not any(q in (x or '').lower() for x in (s.title, s.name, s.text, s.bank, s.group,
                                                              ' '.join(s.levels))):
                continue
            yield s

    def used_in(self, s):
        """Short 'used in' text: Everywhere / one level / one place / n places / '' (unused)."""
        lv = s.levels
        if not lv:
            return ''
        if 'Fix' in lv:
            return 'Everywhere'
        if len(lv) == 1:
            return self.level_names.get(lv[0], lv[0])
        places = sorted({N.place_of(x) for x in lv})
        return places[0] if len(places) == 1 else f'{len(places)} places'

    def summary(self):
        tracks = sum(1 for s in self.list if s.codec == 'seq')
        return dict(banks=len(self.banks), sounds=len(self.list) - tracks, tracks=tracks,
                    voices=sum(1 for s in self.list if s.kind == 'voice'), errors=self.errors[:5])

    def refresh_seconds(self):
        """Fill in MPEG lengths whose bank was decoded since (cheap: WAV sizes) and the tracks' lengths."""
        for s in self.list:
            if s.seconds is None and s.codec != 'seq':
                self._mpeg_seconds(s)
        for s in self.list:
            if s.codec == 'seq' and s.seconds is None and all(p.seconds for p in s.parts):
                s.seconds = sum(p.seconds for p in s.parts)

    # ---- Ubi MPEG via vgmstream ----------------------------------------------------------------------------
    def vgm_dir(self, bank_file):
        st = os.stat(bank_file)
        base = os.path.splitext(os.path.basename(bank_file))[0]
        return os.path.join(self.cache_dir, 'vgm', f'{base}_{st.st_size}_{int(st.st_mtime)}')

    def _mpeg_seconds(self, s):
        p = self.vgm_path(s, decode=False)
        if p:
            s.seconds = max(0, os.path.getsize(p) - 44) / (2 * s.channels * s.rate)
        elif self.vgmstream and not s.external:
            s.seconds = self._meta(s.file).get(s.index)

    def _meta(self, bank_file):
        """{node index: seconds} of a bank's MPEG entries from vgmstream metadata mode (fast, no decoding), cached."""
        if bank_file not in self._vgm_meta:
            import json
            f = self.vgm_dir(bank_file) + '.lengths.json'
            try:
                with open(f, encoding='utf-8') as fh:
                    m = {int(k): v for k, v in json.load(fh).items()}
            except (OSError, ValueError):
                m = vgm_lengths(self.vgmstream, bank_file, os.path.dirname(f))
                os.makedirs(os.path.dirname(f), exist_ok=True)
                with open(f, 'w', encoding='utf-8') as fh:
                    json.dump(m, fh)
            self._vgm_meta[bank_file] = m
        return self._vgm_meta[bank_file]

    def vgm_path(self, s, decode=True, progress=None):
        """Decoded WAV of an MPEG entry; decode=True runs vgmstream on the whole bank the first time."""
        m = self._vgm.get(s.file)
        if m is None:
            d = self.vgm_dir(s.file)
            if not os.path.exists(os.path.join(d, '.done')):
                if not decode:
                    return None
                with self._vgm_lock:
                    if not os.path.exists(os.path.join(d, '.done')):
                        if progress:
                            progress(f'Decoding {s.bank} with vgmstream (first time only)…')
                        vgm_decode_bank(self.vgmstream, s.file, d)
            m = {}
            for f in os.listdir(d):
                g = VGM_NAME.match(f)
                if g:
                    m.setdefault(int(g.group(2)), os.path.join(d, f))
            self._vgm[s.file] = m
        return m.get(s.index)

    # ---- decoding ------------------------------------------------------------------------------------------
    def decode(self, s, progress=None):
        """-> (channels, rate, array('h') interleaved int16 samples). Raises NotAvailable."""
        with self._cache_lock:
            if s.key in self._cache:
                self._cache.move_to_end(s.key)
                return self._cache[s.key]
        r = self._decode(s, progress)
        if s.seconds is None or s.codec == 'seq':
            s.seconds = len(r[2]) / r[0] / r[1]
        with self._cache_lock:
            self._cache[s.key] = r
            while len(self._cache) > CACHE_MAX:
                self._cache.popitem(last=False)
        return r

    def _decode(self, s, progress=None):
        if s.codec == 'seq':
            return join([self.decode(p, progress) for p in s.parts])
        if s.codec == 'stream':
            return _pcm(*B.decode_apm(open(s.file, 'rb').read()))
        if s.external and s.name.lower() in self.apm:
            return _pcm(*B.decode_apm(open(self.apm[s.name.lower()], 'rb').read()))
        if s.external or s.codec == 'mpd':
            p = self.vgm_path(s, progress=progress)
            if p:
                return read_wav(p)
            raise NotAvailable(f'vgmstream did not decode this entry ({s.name}). '
                               f'Log: {os.path.join(self.vgm_dir(s.file), "vgmstream.log")}')
        with open(s.file, 'rb') as f:
            f.seek(s.data)
            raw = f.read(s.size)
        if s.codec == 'pcm':
            n = len(raw) // (2 * s.channels) * 2 * s.channels
            return _pcm(s.channels, s.rate, raw[:n])
        return _pcm(*B.decode_apm(raw))

    def wav_bytes(self, s, progress=None):
        buf = io.BytesIO()
        write_wav(buf, *self.decode(s, progress))
        return buf.getvalue()

    def export(self, s, path):
        write_wav(path, *self.decode(s))
        return path


def join(parts):
    """Concatenate decoded parts; mono parts are doubled to stereo and other rates resampled (nearest) if mixed."""
    ch = max(p[0] for p in parts)
    rate = max(p[1] for p in parts)
    out = array.array('h')
    for c, r, a in parts:
        if r != rate:
            n = len(a) // c
            idx = [int(i * r / rate) for i in range(int(n * rate / r))]
            a = array.array('h', (a[j * c + k] for j in idx for k in range(c)))
        if c < ch:
            b = array.array('h', bytes(2 * len(a) * ch))
            for k in range(ch):
                b[k::ch] = a
            a = b
        out.extend(a)
    return ch, rate, out


def find_vgmstream(path=None):
    """vgmstream-cli path or None: explicit path, $HYPEKIT_VGMSTREAM, a bundled copy (vendor/vgmstream next to the
    package or inside a PyInstaller app), a development checkout's tools folder, then PATH."""
    exe = 'vgmstream-cli.exe' if sys.platform == 'win32' else 'vgmstream-cli'
    here = os.path.dirname(os.path.abspath(__file__))
    bases = [getattr(sys, '_MEIPASS', None), os.path.dirname(here)]
    cands = [path, os.environ.get('HYPEKIT_VGMSTREAM')]
    cands += [os.path.join(b, 'vendor', 'vgmstream', exe) for b in bases if b]
    cands.append(os.path.join(os.path.dirname(os.path.dirname(here)), 'sources', 'tools', 'vgmstream', exe))
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return shutil.which('vgmstream-cli')


_META_NAME = re.compile(r'^stream name: bnm/(\d+)/', re.M)
_META_DUR = re.compile(r'^play duration: (\d+) samples', re.M)
_META_RATE = re.compile(r'^sample rate: (\d+) Hz', re.M)


def vgm_lengths(cli, bank_file, tmp_dir):
    """{node index: seconds} via `vgmstream-cli -m -S 0` (metadata only). Banks with sequence entries vgmstream
    cannot follow are read from a copy with those entries retyped (as in vgm_decode_bank). {} on failure."""
    def run(src):
        try:
            r = subprocess.run([cli, '-m', '-S', '0', src], capture_output=True, text=True, errors='replace', timeout=120,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            return {}
        out = {}
        for block in r.stdout.split('metadata for ')[1:]:
            n, d, rate = _META_NAME.search(block), _META_DUR.search(block), _META_RATE.search(block)
            if n and d and rate and int(rate.group(1)):
                out[int(n.group(1))] = round(int(d.group(1)) / int(rate.group(1)), 3)
        return out
    m = run(bank_file)
    if not m:
        b = bytearray(open(bank_file, 'rb').read())
        h = struct.unpack_from('<11I', b, 0)
        for i in range(h[4]):
            o = h[3] + i * 0x5c
            if struct.unpack_from('<I', b, o + 4)[0] != 1:
                struct.pack_into('<I', b, o + 4, 0x0f)
        os.makedirs(tmp_dir, exist_ok=True)
        fixed = os.path.join(tmp_dir, 'meta_' + os.path.basename(bank_file))
        with open(fixed, 'wb') as f:
            f.write(b)
        try:
            m = run(fixed)
        finally:
            os.remove(fixed)
    return m


def vgm_decode_bank(cli, bank_file, d):
    """vgmstream-cli -S 0 on one bank into d. vgmstream refuses banks with sequence entries it cannot follow
    (it opens the bank they point to and fails): then decode a copy whose non-audio entries are retyped to 0x0f."""
    if not cli:
        raise NotAvailable('Ubi MPEG needs vgmstream-cli: set $HYPEKIT_VGMSTREAM or put it on PATH.')
    os.makedirs(d, exist_ok=True)
    log = []

    def run(src):
        r = subprocess.run([cli, '-S', '0', '-o', os.path.join(d, '?s_?n.wav'), src], capture_output=True,
                           text=True, errors='replace', timeout=600,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        log.append(f'== {src} exit {r.returncode}\n{r.stdout[-4000:]}{r.stderr[-4000:]}')
        return r.returncode == 0
    if not run(bank_file):
        b = bytearray(open(bank_file, 'rb').read())
        h = struct.unpack_from('<11I', b, 0)
        for i in range(h[4]):
            o = h[3] + i * 0x5c
            if struct.unpack_from('<I', b, o + 4)[0] != 1:
                struct.pack_into('<I', b, o + 4, 0x0f)
        fixed = os.path.join(d, os.path.basename(bank_file))
        with open(fixed, 'wb') as f:
            f.write(b)
        run(fixed)
        os.remove(fixed)
    with open(os.path.join(d, 'vgmstream.log'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(log))
    open(os.path.join(d, '.done'), 'w').close()


def _num(p):
    d = ''.join(c for c in os.path.basename(p) if c.isdigit())
    return (int(d) if d else 1 << 30, p.lower())


def _apm_seconds(f):
    with open(f, 'rb') as fh:
        hd = fh.read(8)
    ch, rate = struct.unpack_from('<HI', hd, 2)
    return max(0, os.path.getsize(f) - 0x64) * 2 / max(1, ch) / max(1, rate)


def _pcm(ch, rate, raw):
    a = array.array('h')
    a.frombytes(raw)
    return ch, rate, a


def read_wav(p):
    with wave.open(p) as w:
        if w.getsampwidth() != 2:
            raise NotAvailable(f'{os.path.basename(p)}: {8 * w.getsampwidth()}-bit WAV')
        return _pcm(w.getnchannels(), w.getframerate(), w.readframes(w.getnframes()))


def write_wav(path_or_file, ch, rate, a):
    with wave.open(path_or_file, 'wb') as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(a.tobytes())

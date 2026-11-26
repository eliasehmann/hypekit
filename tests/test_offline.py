"""Tests that need no game install (they run in CI): pure decoders, schema, filters, CLI, packaging metadata."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import hypekit  # noqa: E402
from hypekit import cli, game, query, schema, text, textures  # noqa: E402


class Textures(unittest.TestCase):
    def test_rle_decode(self):
        data = b'\x01\x02' + b'\xff\x07\x03' + b'\x09' + b'\xff\x05\x06'
        planes, end = textures.rle_decode(data, 0, 2, 6, 0xff)
        self.assertEqual(planes, [bytes([1, 2, 7, 7, 7, 9]), bytes([5] * 6)])
        self.assertEqual(end, len(data))

    def test_rle_overflow(self):
        with self.assertRaises(ValueError):
            textures.rle_decode(b'\xff\x07\x09', 0, 1, 4, 0xff)

    def test_mip_sizes(self):
        self.assertEqual(textures.mip_sizes(4, 4, 16), [(4, 4)])
        self.assertEqual(textures.mip_sizes(4, 4, 21), [(4, 4), (2, 2), (1, 1)])
        self.assertEqual(textures.mip_sizes(8, 2, 16 + 4 + 2 + 1), [(8, 2), (4, 1), (2, 1), (1, 1)])
        with self.assertRaises(ValueError):
            textures.mip_sizes(4, 4, 17)

    def test_png_bytes(self):
        rgba = bytes(range(2 * 3 * 4))
        png = textures.png_bytes(2, 3, rgba)
        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', png[16:24]), (2, 3))
        n = struct.unpack('>I', png[33:37])[0]
        self.assertEqual(png[37:41], b'IDAT')
        raw = zlib.decompress(png[41:41 + n])
        self.assertEqual(b''.join(raw[y * 9 + 1:(y + 1) * 9] for y in range(3)), rgba)


class Text(unittest.TestCase):
    """Invented sentences only (no game text). Blocks imitate a .lng: strings separated by NUL / pointer bytes."""
    PL = ['Dzień dobry, mój drogi przyjacielu!', 'Gdzie jest zamek białego króla?', 'Idę już do domu, było późno.',
          'Mała łąka leży za wsią nad rzeką.', 'Wziąłem ze sobą miecz i złotą tarczę.', 'Źle się dziś czuję, mistrzu.']
    WEST = ['¿Dónde está el castillo del rey, señor?', 'Où est le château du roi, mon ami ?',
            'Die Brücke über den Fluß ist zerstört.', 'Mañana iré contigo hasta la montaña.',
            'Vous êtes prêt à forger une épée ?', 'Der König wartet schon auf dich.']

    @staticmethod
    def block(strings, enc):
        return b'\0\x04\x10\0'.join(s.encode(enc) for s in strings)

    def test_detect(self):
        more = ['Kowal zrobił dla mnie nowy miecz.', 'Musisz znaleźć cztery klejnoty, zanim pójdziesz dalej.',
                'Stary mag mieszkał w wieży na wzgórzu.', 'Nie mogłem otworzyć bramy bez klucza.']
        self.assertEqual(text.detect([self.block(self.PL + more, 'cp1250')]), 'cp1250')
        self.assertEqual(text.detect([self.block(self.WEST, 'cp1252')]), 'cp1252')
        self.assertEqual(text.detect([]), 'cp1252')
        self.assertEqual(text.detect([bytes(range(256)) * 50]), 'cp1252')          # binary data is not Polish
        mixed = [self.block(self.WEST * 20, 'cp1252'), self.block(self.PL, 'cp1250')]   # a few stray hits
        self.assertEqual(text.detect(mixed), 'cp1252')

    def test_polish(self):
        words = ['źródło', 'żółty ', 'łąkę ']          # highlighted words are separate strings, mostly high bytes
        data = self.block(['hero_sequence1', 'ŻÓŁTY RYCERZ :'] + self.PL + words + ['idź'], 'cp1250')
        frags = text.scan(data, 'cp1250')
        self.assertEqual(frags[:2], [('seq', 'hero_sequence1'), ('who', 'ŻÓŁTY RYCERZ')])
        want = self.PL + [w.strip() for w in words]    # 'idź': up to 4 bytes without a space is dropped, like 'Oui'
        self.assertEqual([s.strip() for k, s in frags[2:]], want)
        self.assertEqual(text.turns(frags), [('hero_sequence1', 'ŻÓŁTY RYCERZ', ' '.join(want))])
        wrong = ''.join(s for k, s in text.scan(data, 'cp1252'))                  # what 1.0.0 showed
        self.assertIn('³', wrong)
        self.assertNotIn('ł', wrong)

    def test_western_unchanged(self):
        junk = b'\0X \xf1\0\xc7\xd0\xd6\xde\0AB\xe9\0'                               # pointer bytes: dropped
        data = self.block(['guard_sequence2', 'EL SEÑOR :'] + self.WEST, 'cp1252') + junk
        self.assertEqual(text.scan(data), [('seq', 'guard_sequence2'), ('who', 'EL SEÑOR')]
                         + [('txt', s + ' ') for s in self.WEST])

    def test_install_encoding(self):
        old = os.environ.pop(text.ENV_ENCODING, None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(text.install_encoding(tmp), 'cp1252')            # nothing to read: the default
                os.environ[text.ENV_ENCODING] = 'windows-1250'
                self.assertEqual(text.install_encoding(tmp), 'cp1250')
                os.environ[text.ENV_ENCODING] = 'no-such-codec'
                with self.assertRaises(ValueError):
                    text.install_encoding(tmp)
        finally:
            os.environ.pop(text.ENV_ENCODING, None)
            if old is not None:
                os.environ[text.ENV_ENCODING] = old


class Game(unittest.TestCase):
    def test_ci_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'Gamedata', 'World', 'Levels'))
            hit = game.ci_path(tmp, 'gamedata', 'WORLD', 'levels')
            self.assertTrue(hit and os.path.isdir(hit))
            self.assertIsNone(game.ci_path(tmp, 'gamedata', 'nothing'))
            self.assertIsNone(game.ci_path(os.path.join(tmp, 'missing'), 'x'))
            self.assertFalse(game.is_game(tmp))


class Schema(unittest.TestCase):
    def test_json_schema(self):
        all_ = schema.json_schema()
        self.assertLessEqual({'sound', 'line', 'texture', 'perso', 'save'}, set(all_))
        for kind, s in all_.items():
            self.assertEqual(s['$id'], f'hypekit/{kind}/v{schema.VERSION}')
            self.assertIn('id', s['properties'])
        json.dumps(all_)

    def test_cli_schema(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(['schema', 'sound'])
        self.assertEqual(json.loads(out.getvalue())['title'], 'sound')


class Query(unittest.TestCase):
    def test_vals(self):
        self.assertEqual(query.vals('a,b,'), ['a', 'b'])
        self.assertEqual(query.vals(['a', '', 3]), ['a', '3'])
        self.assertEqual(query.vals(None), [])
        self.assertEqual(query.vals(''), [])

    def test_like_escapes(self):
        self.assertEqual(query._like('50%_a'), '%50\\%\\_a%')


class Package(unittest.TestCase):
    def test_version(self):
        self.assertRegex(hypekit.__version__, r'^\d+\.\d+\.\d+$')
        with open(os.path.join(ROOT, 'CHANGELOG.md'), encoding='utf-8') as f:
            self.assertIn(f'## [{hypekit.__version__}]', f.read())

    def test_web_files(self):
        web = os.path.join(os.path.dirname(hypekit.__file__), 'web')
        for rel in ('index.html', 'app.js', 'viewer.js', 'style.css', 'fonts/inter-var.woff2',
                    'vendor/three/three.module.min.js', 'vendor/three/LICENSE'):
            self.assertTrue(os.path.isfile(os.path.join(web, *rel.split('/'))), rel)

    def test_no_game_error(self):
        if game.find_game():
            self.skipTest('an install is present')
        with self.assertRaises(FileNotFoundError):
            hypekit.open()


if __name__ == '__main__':
    unittest.main()

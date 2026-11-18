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
from hypekit import cli, game, query, schema, textures  # noqa: E402


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

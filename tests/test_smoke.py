"""Smoke tests against the auto-detected install (skipped without one)."""
import io
import os
import struct
import sys
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hypekit  # noqa: E402
from hypekit import game, schema  # noqa: E402

GAME = game.find_game()


@unittest.skipUnless(GAME, 'no Hype install found ($HYPEKIT_GAME)')
class Smoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kit = hypekit.open(GAME)
        cls.meta = cls.kit.build()

    @classmethod
    def tearDownClass(cls):
        cls.kit.close()

    def test_counts(self):
        self.assertGreater(int(self.meta['sounds']), 1000)
        self.assertGreater(int(self.meta['lines']), 500)
        self.assertGreater(int(self.meta['textures']), 1000)
        self.assertGreater(int(self.meta['links']), 100)

    def test_records_match_schema(self):
        for kind, rows in (('sound', self.kit.sounds(limit=5)), ('line', self.kit.lines(limit=5)),
                           ('texture', self.kit.textures(limit=5))):
            props = schema.RECORDS[kind]['properties']
            for r in rows:
                self.assertEqual(set(r), set(props), kind)

    def test_voice_links_line(self):
        v = self.kit.sounds(kind='voice', limit=1)[0]
        r = self.kit.get(v['id'])
        self.assertTrue(r['lines'])
        back = self.kit.get(r['lines'][0]['id'])
        self.assertIn(v['id'], [s['id'] for s in back['sounds']])

    def test_pcm_or_apm_wav(self):
        s = self.kit.sql("SELECT id FROM sounds WHERE format IN ('PCM', 'APM') LIMIT 1")[0]
        with wave.open(io.BytesIO(self.kit.wav(s['id']))) as w:
            self.assertGreater(w.getnframes(), 0)

    def test_png(self):
        for arch in ('Textures', 'Vignette'):
            t = self.kit.textures(archive=arch, limit=1)[0]
            png = self.kit.png(t['id'])
            self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II', png[16:24]), (t['width'], t['height']))

    def test_character_glb(self):
        from hypekit import characters, level
        lv = self.kit.game.model_levels()[0]
        recs = characters.scan_level(level.load(self.kit.game, lv))
        self.assertTrue(recs)
        self.assertEqual(set(recs[0]), set(schema.RECORDS['perso']['properties']))
        r = max(recs, key=lambda x: x['parts'])
        info = self.kit.perso(r['id'])
        self.assertTrue(info['animations'])
        glb = self.kit.glb(r['id'], info['animations'][0]['index'])
        self.assertEqual(glb[:4], b'glTF')
        n = struct.unpack_from('<I', glb, 12)[0]
        g = __import__('json').loads(glb[20:20 + n])
        self.assertTrue(g['meshes'])
        self.assertTrue(g.get('images'), 'textures resolved from Textures.cnt')

    def test_saves(self):
        slots = self.kit.saves()
        if not slots:
            self.skipTest('no save games in this install')
        s = self.kit.save(slots[0]['id'])
        self.assertEqual(set(s) - {'place'}, set(schema.RECORDS['save']['properties']) - {'place'})
        self.assertGreater(s['records'], 100)
        self.assertTrue(s['health_max'])

    def test_not_found(self):
        with self.assertRaises(hypekit.NotFound):
            self.kit.get('nope:0')


if __name__ == '__main__':
    unittest.main()

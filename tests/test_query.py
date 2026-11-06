"""Filters, facets and sorting (query.py) against the auto-detected install (skipped without one)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hypekit  # noqa: E402
from hypekit import game, query as Q  # noqa: E402

GAME = game.find_game()


@unittest.skipUnless(GAME, 'no Hype install found ($HYPEKIT_GAME)')
class Query(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kit = hypekit.open(GAME)
        cls.kit.build()

    @classmethod
    def tearDownClass(cls):
        cls.kit.close()

    def test_lengths_known(self):
        self.assertEqual(self.kit.sql('SELECT count(*) AS n FROM sounds WHERE seconds IS NULL')[0]['n'], 0)

    def test_sound_facets_add_up(self):
        all_ = Q.sounds(self.kit, {}, limit=1)['total']
        f = Q.sound_facets(self.kit, {})
        self.assertEqual(sum(v for k, v in f['kind'].items() if k != 'music part'), all_)
        self.assertEqual(sum(f['length'].values()), all_)

    def test_filters_combine(self):
        voice = Q.sounds(self.kit, {'kind': 'voice'}, limit=1)['total']
        long_voice = Q.sounds(self.kit, {'kind': 'voice', 'length': 'long'}, limit=1)['total']
        two = Q.sounds(self.kit, {'kind': 'voice,music'}, limit=1)['total']
        self.assertTrue(0 < long_voice < voice < two)
        self.assertEqual(Q.sounds(self.kit, {'ids': ''}, limit=1)['total'], 0)

    def test_sort(self):
        r = Q.sounds(self.kit, {'kind': 'music'}, limit=5, sort='long')['items']
        self.assertEqual([x['seconds'] for x in r], sorted((x['seconds'] for x in r), reverse=True))

    def test_texture_buckets(self):
        total = Q.textures(self.kit, {}, limit=1)['total']
        f = Q.texture_facets(self.kit, {})
        self.assertEqual(sum(f['size'].values()), total)
        self.assertEqual(sum(f['format'].values()), total)
        big = Q.textures(self.kit, {'size': 'large,huge'}, limit=500, sort='large')['items']
        self.assertTrue(big and all(max(t['width'], t['height']) > 128 for t in big))

    def test_lines_voiced(self):
        f = Q.line_facets(self.kit, {})
        total = Q.lines(self.kit, {}, limit=1)['total']
        self.assertEqual(f['voiced']['1'] + f['voiced']['0'], total)
        r = Q.lines(self.kit, {'voiced': '1'}, limit=20)['items']
        self.assertTrue(all(x['sounds'] for x in r))


if __name__ == '__main__':
    unittest.main()

"""HTTP API tests: a server on a free port against the auto-detected install (skipped without one)."""
import json
import os
import sys
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hypekit  # noqa: E402
from hypekit import game, server  # noqa: E402

GAME = game.find_game()


@unittest.skipUnless(GAME, 'no Hype install found ($HYPEKIT_GAME)')
class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kit = hypekit.open(GAME)
        cls.srv, cls.url = server.serve(cls.kit, 0)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.kit.close()

    def fetch(self, path, headers=None):
        req = urllib.request.Request(self.url + path.lstrip('/'), headers=headers or {})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.headers, r.read()

    def json(self, path):
        return json.loads(self.fetch(path)[2])

    def test_lists(self):
        self.assertEqual(len(self.json('/api/sounds?limit=5')), 5)
        a, b = self.json('/api/sounds?limit=3'), self.json('/api/sounds?limit=3&offset=1')
        self.assertEqual(a[1]['id'], b[0]['id'])
        self.assertTrue(self.json('/api/levels'))
        self.assertIn('sounds', self.json('/api/find?q=a'))

    def test_script_has_voice_ids(self):
        lv = next(l['level'] for l in self.json('/api/levels') if l['level'] != 'Fix')
        lines = self.json(f'/api/script/{lv}')
        self.assertTrue(lines)
        self.assertTrue(all(isinstance(l['sounds'], list) for l in lines))

    def test_png_and_range(self):
        t = self.json('/api/textures?limit=1')[0]
        st, h, body = self.fetch(f'/api/png/{t["id"]}')
        self.assertEqual((st, h['Content-Type'], body[:4]), (200, 'image/png', b'\x89PNG'))
        st, h, body = self.fetch(f'/api/png/{t["id"]}', {'Range': 'bytes=0-9'})
        self.assertEqual((st, len(body)), (206, 10))

    def test_errors(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.fetch('/api/get/nope:0')
        self.assertEqual(cm.exception.code, 404)

    def test_static_no_escape(self):
        st, h, body = self.fetch('/../../README.md')
        self.assertIn(b'<!DOCTYPE html>', body)      # falls back to the app, never a file outside web/


if __name__ == '__main__':
    unittest.main()

"""The default player's data contract, using only generated synthetic work."""
import gc
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'service'))
import melange_service as service


@unittest.skipIf(sys.platform == 'win32', 'flagship recording uses a POSIX terminal')
class TestPlayerService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='melange-player-')
        self.previous = service.REGISTRY
        service.REGISTRY = service.StoreRegistry({'stores': {'example': {
            'label': 'Synthetic example', 'generate': 'flagship',
            'path': str(Path(self.tmp.name) / 'demo' / 'timeline')}}})
        self.server = service.ThreadingHTTPServer(('127.0.0.1', 0), service.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        service.REGISTRY = self.previous
        gc.collect()
        self.tmp.cleanup()

    def api(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)

    def test_fresh_example_has_timed_navigable_steps_and_persisted_notes(self):
        stores = self.api('/api/stores')
        self.assertTrue(stores[0]['branches'])
        path = '/api/store/example/branch/main'
        detail = self.api(path)
        self.assertTrue(detail['seal'])
        self.assertEqual(len(detail['timeline']), detail['steps'])
        stamps = [entry['ts'] for entry in detail['timeline']]
        self.assertEqual(stamps, sorted(stamps))
        step = detail['computation_step']
        frame = self.api(path + f'/step/{step}')
        self.assertEqual(frame['event_id'], detail['timeline'][step - 1]['event_id'])
        self.assertEqual(frame['payload']['figures']['/totalTax'], 3568)
        self.api(path + '/note', {'step': step, 'text': 'Synthetic player note'})
        reopened = self.api(path)
        self.assertEqual(reopened['notes'][-1]['at_event'], frame['event_id'])
        self.assertEqual(reopened['notes'][-1]['text'], 'Synthetic player note')
        self.assertTrue(reopened['seal'])

    def test_correction_opens_a_real_result_and_preserves_original(self):
        path = '/api/store/example/branch/main'
        before = self.api(path)
        original = self.api(path + f"/step/{before['computation_step']}")
        result = self.api(path + '/fork', {'clamp': {'cell': '/wages', 'value': 48000}})
        changed_path = '/api/store/example/branch/' + result['branch']
        changed = self.api(changed_path)
        self.assertEqual(changed['computation_step'], changed['steps'])
        frame = self.api(changed_path + f"/step/{changed['steps']}")
        self.assertEqual(changed['computation']['inputs']['/wages'], 48000)
        self.assertEqual(frame['payload']['figures']['/totalTax'], 3088)
        self.assertEqual(frame['payload']['figures']['/refund'], 3012)
        self.assertEqual(self.api(path + f"/step/{before['computation_step']}"), original)
        self.assertEqual(self.api(path)['computation']['inputs']['/wages'], 52000)
        self.assertTrue(changed['seal'])

    def test_browser_assets_are_served_with_executable_mime_types(self):
        for path, expected in [('/', 'text/html'),
                               ('/static/player.js', 'text/javascript'),
                               ('/static/player.css', 'text/css'),
                               ('/static/advanced.html', 'text/html')]:
            with self.subTest(path=path), urllib.request.urlopen(self.base + path) as response:
                self.assertEqual(response.headers.get_content_type(), expected)
                self.assertTrue(response.read())


if __name__ == '__main__':
    unittest.main()

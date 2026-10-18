import io
from pathlib import Path
import sys
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from watch_screen_model import read_new_rows


class ScreenWatchTests(TestCase):
    def test_incomplete_line_is_retried_and_malformed_complete_line_skipped(self):
        source = io.StringIO('{"id":1}\ninvalid\n[]\n{"id":2')
        self.assertEqual(list(read_new_rows(source)), [{'id': 1}])
        pending = source.tell()
        self.assertEqual(list(read_new_rows(source)), [])
        source.seek(0, 2)
        source.write('}\n')
        source.seek(pending)
        self.assertEqual(list(read_new_rows(source)), [{'id': 2}])

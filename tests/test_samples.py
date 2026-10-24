import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class SampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.script = Path(self.temp.name) / 'make_samples.py'
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'examples' / 'make_samples.py', self.script)
        self.generated = self.script.parent / 'generated'

    def run_generator(self, expected=0):
        result = subprocess.run([sys.executable, str(self.script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_samples_are_idempotent(self):
        self.run_generator()
        old = {p.name: p.read_bytes() for p in self.generated.iterdir()}
        self.run_generator()
        self.assertEqual(old, {p.name: p.read_bytes() for p in self.generated.iterdir()})
        self.assertEqual(set(json.loads(old['samples.json'])), {'before.db', 'after.db', 'keyless.db'})

    def test_existing_user_file_is_not_overwritten(self):
        self.generated.mkdir()
        path = self.generated / 'before.db'
        path.write_bytes(b'user data')
        self.run_generator(expected=2)
        self.assertEqual(path.read_bytes(), b'user data')
        self.assertFalse((self.generated / 'after.db').exists())

    def test_modified_samples_are_not_overwritten(self):
        self.run_generator()
        path = self.generated / 'before.db'
        path.write_bytes(b'modified')
        self.run_generator(expected=2)
        self.assertEqual(path.read_bytes(), b'modified')


if __name__ == '__main__':
    unittest.main()

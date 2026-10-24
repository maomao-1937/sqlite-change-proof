from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'sqlite_change_proof.py'


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.a = Path(self.temp.name) / 'before # ü.db'
        self.b = Path(self.temp.name) / 'after.db'

    def db(self, path, ddl='CREATE TABLE items(id INTEGER PRIMARY KEY, value)', rows=()):
        with closing(sqlite3.connect(path)) as con, con:
            con.execute(ddl)
            if rows:
                con.executemany('INSERT INTO items VALUES (?, ?)', rows)

    def run_cli(self, *extra, tables=('items',), expected=0):
        args = [sys.executable, str(SCRIPT), str(self.a), str(self.b), '--format', 'json']
        for table in tables:
            args += ['--table', table]
        result = subprocess.run(args + list(extra), text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout) if result.stdout else result.stderr

    def test_script_exists(self):
        self.assertTrue(SCRIPT.is_file(), 'CLI implementation is missing')

    def test_insert_delete_update_and_blob_evidence(self):
        self.db(self.a, rows=[(1, 'old'), (2, 'removed')])
        self.db(self.b, rows=[(1, b'\x00\xff'), (3, 'added')])
        table = self.run_cli(expected=1)['tables'][0]
        self.assertEqual(table['counts'], {'inserted': 1, 'deleted': 1, 'updated': 1})
        change = table['rows']['updated'][0]['changed_columns']['value']
        self.assertEqual(change['after'], {'type': 'blob', 'base64': 'AP8='})
        self.assertEqual(change['before'], {'type': 'text', 'value': 'old'})

    def test_identical_sources_not_modified(self):
        self.db(self.a, rows=[(1, None)])
        self.db(self.b, rows=[(1, None)])
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (self.a, self.b)]
        self.assertEqual(self.run_cli()['status'], 'verified_same')
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in (self.a, self.b)])

    def test_integer_and_float_cells_differ(self):
        self.db(self.a, rows=[(1, 1)])
        self.db(self.b, rows=[(1, 1.0)])
        self.assertEqual(self.run_cli(expected=1)['tables'][0]['counts']['updated'], 1)

    def test_composite_primary_key(self):
        ddl = 'CREATE TABLE items(a TEXT, b INTEGER, value, PRIMARY KEY(a,b))'
        for path, value in [(self.a, 'x'), (self.b, 'y')]:
            self.db(path, ddl)
            with closing(sqlite3.connect(path)) as con, con:
                con.execute('INSERT INTO items VALUES (?,?,?)', ('key', 2, value))
        table = self.run_cli(expected=1)['tables'][0]
        self.assertEqual(table['primary_key'], ['a', 'b'])
        self.assertEqual(table['counts']['updated'], 1)

    def test_nullable_primary_key_is_unverified(self):
        ddl = 'CREATE TABLE items(id TEXT PRIMARY KEY, value)'
        self.db(self.a, ddl, [(None, 'sensitive')])
        self.db(self.b, ddl, [(None, 'sensitive')])
        self.assertIn('null_primary_key', self.run_cli(expected=3)['tables'][0]['reason'])

    def test_keyless_is_unverified(self):
        for path in (self.a, self.b):
            self.db(path, 'CREATE TABLE items(id, value)', [(1, 'x')])
        self.assertEqual(self.run_cli(expected=3)['tables'][0]['reason'], 'no_declared_primary_key')

    def test_schema_change_does_not_pair_rows(self):
        self.db(self.a)
        self.db(self.b, 'CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT)')
        table = self.run_cli(expected=3)['tables'][0]
        self.assertEqual(table['status'], 'schema_changed')
        self.assertTrue(table['row_comparison_unverified'])
        self.assertNotIn('counts', table)

    def test_added_and_removed_table(self):
        self.db(self.a)
        with closing(sqlite3.connect(self.b)) as con, con:
            con.execute('CREATE TABLE other(id INTEGER PRIMARY KEY)')
        report = self.run_cli(tables=('items', 'other'), expected=3)
        self.assertEqual([t['status'] for t in report['tables']], ['table_removed', 'table_added'])

    def test_view_is_unverified(self):
        for path in (self.a, self.b):
            self.db(path, 'CREATE VIEW items AS SELECT 1 AS id')
        self.assertEqual(self.run_cli(expected=3)['tables'][0]['reason'], 'unsupported_table_kind')

    def test_generated_column_is_unverified(self):
        for path in (self.a, self.b):
            self.db(path, 'CREATE TABLE items(id INTEGER PRIMARY KEY, value AS (id+1))')
        self.assertEqual(self.run_cli(expected=3)['tables'][0]['reason'], 'generated_or_hidden_columns')

    def test_collation_requires_review(self):
        for path in (self.a, self.b):
            self.db(path, 'CREATE TABLE items(id TEXT PRIMARY KEY COLLATE NOCASE, value)')
        self.assertEqual(self.run_cli(expected=3)['tables'][0]['reason'], 'collation_requires_review')

    def test_quoted_identifier(self):
        for path in (self.a, self.b):
            self.db(path, 'CREATE TABLE "weird""; name"(id INTEGER PRIMARY KEY, value)')
        self.assertEqual(self.run_cli(tables=('weird"; name',))['status'], 'verified_same')

    def test_row_limit(self):
        for path in (self.a, self.b):
            self.db(path, rows=[(i, 'x') for i in range(5001)])
        self.assertEqual(self.run_cli(expected=3)['tables'][0]['reason'], 'row_limit_exceeded')

    def test_column_limit(self):
        ddl = 'CREATE TABLE items(id INTEGER PRIMARY KEY,' + ','.join('c'+str(i) for i in range(100)) + ')'
        for path in (self.a, self.b):
            self.db(path, ddl)
        self.assertEqual(self.run_cli(expected=3)['tables'][0]['reason'], 'column_limit_exceeded')

    def test_companion_file_rejected(self):
        self.db(self.a)
        self.db(self.b)
        for suffix in ('-wal', '-shm', '-journal'):
            companion = Path(str(self.a) + suffix)
            companion.write_bytes(b'')
            self.assertIn('companion', self.run_cli(expected=2))
            companion.unlink()

    def test_missing_file_and_errors_redact_values(self):
        self.db(self.a, rows=[(1, 'private-payload')])
        error = self.run_cli(expected=2)
        self.assertNotIn('private-payload', error)
        self.assertFalse(self.b.exists())
        self.b.write_bytes(b'private-payload not a database')
        self.assertNotIn('private-payload', self.run_cli(expected=2))

    def test_missing_selected_table_is_input_error(self):
        self.db(self.a)
        self.db(self.b)
        self.assertIn('selected table', self.run_cli(tables=('absent',), expected=2))

    def test_text_output_and_fail_flag(self):
        self.db(self.a, rows=[(1, 'a')])
        self.db(self.b, rows=[(1, 'b')])
        args = [sys.executable, str(SCRIPT), str(self.a), str(self.b), '--table', 'items', '--format', 'text', '--fail-on-changes']
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('updated=1', result.stdout)

    def test_changed_source_detection(self):
        sys.path.insert(0, str(ROOT))
        self.addCleanup(lambda: sys.path.remove(str(ROOT)))
        import sqlite_change_proof as proof
        self.db(self.a)
        self.db(self.b)
        real = proof.read_snapshot
        initial_size = self.a.stat().st_size
        mutations = []
        def changing(path, tables):
            answer = real(path, tables)
            # compare() resolves paths; Windows TEMP may use an 8.3 alias.
            # Trigger on actual file identity, not the path's lexical spelling.
            if Path(path).samefile(self.b):
                with self.a.open('ab') as stream:
                    stream.write(b'changed')
                mutations.append(path)
            return answer
        with patch.object(proof, 'read_snapshot', side_effect=changing):
            with self.assertRaisesRegex(proof.InputError, 'changed'):
                proof.compare(self.a, self.b, ['items'])
        self.assertEqual(len(mutations), 1, 'mutation hook must execute exactly once')
        self.assertEqual(self.a.stat().st_size, initial_size + len(b'changed'))

    def test_changed_source_detection_with_dotdot_alias(self):
        component = self.b.parent / 'alias-component'
        component.mkdir()
        self.b = component / '..' / self.b.name
        self.assertNotEqual(self.b, self.b.resolve())
        self.test_changed_source_detection()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows short-path aliases only')
    def test_changed_source_detection_with_windows_short_path(self):
        import ctypes
        from ctypes import wintypes
        directory = self.b.parent / 'directory with spaces'
        directory.mkdir()
        get_short_path = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
        get_short_path.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
        get_short_path.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_short_path(str(directory), buffer, len(buffer))
        if not length or length >= len(buffer) or Path(buffer.value) == directory:
            self.skipTest('8.3 short-name creation unavailable on this volume')
        self.b = Path(buffer.value) / self.b.name
        self.assertNotEqual(self.b, self.b.resolve())
        self.test_changed_source_detection()

    def test_virtual_and_shadow_are_unverified(self):
        for path in (self.a, self.b):
            self.db(path, 'CREATE VIRTUAL TABLE items USING fts5(value)')
        for name in ('items', 'items_data'):
            self.assertEqual(self.run_cli(tables=(name,), expected=3)['tables'][0]['reason'], 'unsupported_table_kind')

    def test_oversized_database_is_input_error(self):
        self.db(self.a)
        self.db(self.b)
        with self.a.open('ab') as stream:
            stream.truncate(32 * 1024 * 1024 + 1)
        self.assertIn('32 MiB', self.run_cli(expected=2))

    def test_unselected_tables_are_not_reported_and_unverified_has_priority(self):
        self.db(self.a, rows=[(1, 'a')])
        self.db(self.b, rows=[(1, 'b')])
        for path in (self.a, self.b):
            with closing(sqlite3.connect(path)) as con, con:
                con.execute('CREATE TABLE keyless(secret)')
        self.assertEqual(len(self.run_cli(expected=1)['tables']), 1)
        report = self.run_cli(tables=('items', 'keyless'), expected=3)
        self.assertTrue(report['changes_detected'])

    def test_duplicate_primary_key_is_detected(self):
        # A deliberately inconsistent synthetic schema tests validation rather than
        # assuming the declared PK is proof of uniqueness in an input snapshot.
        for path in (self.a, self.b):
            self.db(path, 'CREATE TABLE items(id TEXT, value)', [('x', 'one'), ('x', 'two')])
            with closing(sqlite3.connect(path)) as con, con:
                con.execute('PRAGMA writable_schema=ON')
                con.execute("UPDATE sqlite_schema SET sql='CREATE TABLE items(id TEXT PRIMARY KEY, value)' WHERE name='items'")
        self.assertEqual(self.run_cli(expected=3)['tables'][0]['reason'], 'duplicate_primary_key')


if __name__ == '__main__':
    unittest.main()

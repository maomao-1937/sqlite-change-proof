#!/usr/bin/env python3
"""Create only the reserved examples/generated files; never overwrite existing data."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

DIRECTORY = Path(__file__).resolve().parent / 'generated'
NAMES = ('before.db', 'after.db', 'keyless.db')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    try:
        if DIRECTORY.is_symlink():
            raise ValueError('reserved sample directory must not be a symlink')
        DIRECTORY.mkdir(exist_ok=True)
        manifest = DIRECTORY / 'samples.json'
        paths = [DIRECTORY / name for name in NAMES]
        if manifest.exists():
            recorded = json.loads(manifest.read_text(encoding='utf-8'))
            if recorded != {p.name: digest(p) for p in paths} or any(p.is_symlink() for p in paths):
                raise ValueError('existing samples differ; refusing to overwrite')
            print('Synthetic samples already present and unchanged.')
            return 0
        if any(p.exists() or p.is_symlink() for p in paths):
            raise ValueError('reserved sample files exist; refusing to overwrite')
        for path in paths:
            # Exclusive file creation prevents silently opening a user database.
            with path.open('xb'):
                pass
            with closing(sqlite3.connect(path)) as con, con:
                if path.name == 'keyless.db':
                    con.execute('CREATE TABLE events(message TEXT)')
                    con.execute('INSERT INTO events VALUES (?)', ('synthetic event',))
                else:
                    con.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY, title TEXT, payload BLOB)')
                    rows = [(1, 'draft', b'one'), (2, 'remove me', b'two')] if path.name == 'before.db' else [(1, 'reviewed', b'one'), (3, 'new task', b'\x00\xff')]
                    con.executemany('INSERT INTO tasks VALUES (?,?,?)', rows)
        with manifest.open('x', encoding='utf-8') as stream:
            json.dump({p.name: digest(p) for p in paths}, stream, indent=2)
        print('Created synthetic examples/generated/{before,after,keyless}.db')
        return 0
    except (OSError, ValueError, sqlite3.Error):
        print('error: reserved samples are inaccessible or changed; no existing database was overwritten', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

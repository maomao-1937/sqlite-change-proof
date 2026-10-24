#!/usr/bin/env python3
"""Bounded, read-only evidence for explicitly selected SQLite snapshot tables."""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3
import stat
import sys

MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 100
MIN_SQLITE = (3, 37, 0)


class InputError(Exception):
    """Safe, value-free diagnostic suitable for stderr."""


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def fingerprint(path):
    try:
        for suffix in ('-wal', '-shm', '-journal'):
            if Path(str(path) + suffix).exists():
                raise InputError('snapshot has a SQLite companion file; close and export it first')
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise InputError('snapshot must be an existing regular file')
        if info.st_size > MAX_BYTES:
            raise InputError('snapshot exceeds the 32 MiB file limit')
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    except OSError:
        raise InputError('snapshot is missing or inaccessible') from None


def typed(value):
    if value is None:
        return {'type': 'null'}
    if isinstance(value, bytes):
        return {'type': 'blob', 'base64': base64.b64encode(value).decode('ascii')}
    if isinstance(value, int):
        return {'type': 'integer', 'value': value}
    if isinstance(value, float):
        # SQLite may hold infinities. JSON must remain strict and portable.
        return {'type': 'real', 'value': value if math.isfinite(value) else str(value)}
    return {'type': 'text', 'value': value}


def cell_identity(value):
    cell = typed(value)
    return json.dumps(cell, sort_keys=True, ensure_ascii=True, allow_nan=False)


def unverified(reason):
    return {'reason': reason}


def read_snapshot(path, tables):
    """Read only ordinary main-schema tables; callers check stability around both reads."""
    uri = Path(path).resolve().as_uri() + '?mode=ro&immutable=1'
    output = {}
    try:
        with closing(sqlite3.connect(uri, uri=True)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('PRAGMA trusted_schema=OFF')
            con.execute('PRAGMA cache_size=-2048')
            # This connection never enables extension loading or accepts arbitrary SQL.
            budget = [0]
            def progress():
                budget[0] += 1
                return int(budget[0] > 10000)
            con.set_progress_handler(progress, 1000)
            kinds = {row[1]: row[2] for row in con.execute('PRAGMA main.table_list') if row[0] == 'main'}
            for name in tables:
                if name not in kinds:
                    output[name] = None
                    continue
                if kinds[name] != 'table' or name.startswith('sqlite_'):
                    output[name] = unverified('unsupported_table_kind')
                    continue
                sql_row = con.execute('SELECT sql FROM main.sqlite_schema WHERE name=? AND type=?', (name, 'table')).fetchone()
                if not sql_row or not sql_row[0]:
                    output[name] = unverified('unsupported_schema')
                    continue
                sql = sql_row[0]
                columns = list(con.execute('PRAGMA main.table_xinfo(' + quote_identifier(name) + ')'))
                entry = {'schema': {'sql': sql, 'columns': [list(c) for c in columns]}}
                output[name] = entry
                if len(columns) > MAX_COLUMNS:
                    entry.update(unverified('column_limit_exceeded'))
                    continue
                if any(column[6] for column in columns):
                    entry.update(unverified('generated_or_hidden_columns'))
                    continue
                # Conservative: even explicit BINARY or COLLATE in a string/comment asks for review.
                if re.search(r'\bCOLLATE\b', sql, re.IGNORECASE):
                    entry.update(unverified('collation_requires_review'))
                    continue
                pk = sorted((c for c in columns if c[5]), key=lambda c: c[5])
                if not pk:
                    entry.update(unverified('no_declared_primary_key'))
                    continue
                names = [c[1] for c in columns]
                pk_names = [c[1] for c in pk]
                pk_indexes = [names.index(n) for n in pk_names]
                rows = con.execute('SELECT ' + ','.join(quote_identifier(n) for n in names) + ' FROM main.' + quote_identifier(name) + ' LIMIT ' + str(MAX_ROWS + 1)).fetchall()
                if len(rows) > MAX_ROWS:
                    entry.update(unverified('row_limit_exceeded'))
                    continue
                keyed = {}
                for row in rows:
                    key_values = [row[i] for i in pk_indexes]
                    if any(value is None for value in key_values):
                        entry.update(unverified('null_primary_key'))
                        break
                    key = tuple(cell_identity(value) for value in key_values)
                    if key in keyed:
                        entry.update(unverified('duplicate_primary_key'))
                        break
                    keyed[key] = row
                else:
                    entry.update({'names': names, 'primary_key': pk_names, 'pk_indexes': pk_indexes, 'rows': keyed})
    except (sqlite3.Error, UnicodeError, ValueError, OverflowError):
        raise InputError('snapshot could not be read safely as SQLite') from None
    return output


def compare(before, after, tables):
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise InputError('SQLite 3.37.0 or newer is required')
    if not tables or any(not t or '\x00' in t for t in tables):
        raise InputError('at least one valid selected table name is required')
    paths = [Path(before).resolve(), Path(after).resolve()]
    initial = [fingerprint(path) for path in paths]
    names = list(dict.fromkeys(tables))
    left = read_snapshot(paths[0], names)
    right = read_snapshot(paths[1], names)
    if initial != [fingerprint(path) for path in paths]:
        raise InputError('snapshot changed during comparison; offline snapshots are required')
    changed = False
    incomplete = False
    results = []
    for name in names:
        a, b = left[name], right[name]
        result = {'table': name}
        results.append(result)
        if a is None and b is None:
            raise InputError('selected table does not exist in either snapshot')
        if a is None or b is None:
            result.update({'status': 'table_added' if a is None else 'table_removed', 'row_comparison_unverified': True})
            changed = incomplete = True
            continue
        if a.get('schema') is not None and b.get('schema') is not None and a['schema'] != b['schema']:
            result.update({'status': 'schema_changed', 'row_comparison_unverified': True, 'before_schema': a['schema'], 'after_schema': b['schema']})
            changed = incomplete = True
            continue
        if 'reason' in a or 'reason' in b:
            result.update({'status': 'review_unverified', 'reason': a.get('reason') or b.get('reason'), 'row_comparison_unverified': True})
            incomplete = True
            continue
        evidence = {'inserted': [], 'deleted': [], 'updated': []}
        result['primary_key'] = a['primary_key']
        def key_evidence(row, source):
            return {col: typed(row[index]) for col, index in zip(source['primary_key'], source['pk_indexes'])}
        for key in sorted(a['rows'].keys() | b['rows'].keys()):
            old, new = a['rows'].get(key), b['rows'].get(key)
            if old is None:
                evidence['inserted'].append({'key': key_evidence(new, b), 'row': {col: typed(value) for col, value in zip(b['names'], new)}})
            elif new is None:
                evidence['deleted'].append({'key': key_evidence(old, a), 'row': {col: typed(value) for col, value in zip(a['names'], old)}})
            else:
                delta = {col: {'before': typed(x), 'after': typed(y)} for col, x, y in zip(a['names'], old, new) if cell_identity(x) != cell_identity(y)}
                if delta:
                    evidence['updated'].append({'key': key_evidence(old, a), 'changed_columns': delta})
        counts = {kind: len(rows) for kind, rows in evidence.items()}
        table_changed = any(counts.values())
        changed |= table_changed
        result.update({'status': 'changed' if table_changed else 'same', 'counts': counts, 'rows': evidence})
    return {'format_version': 1, 'status': 'review_unverified' if incomplete else ('changes' if changed else 'verified_same'), 'changes_detected': changed, 'tables': results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--table', action='append', required=True, help='exact main-schema table name; repeat to select more')
    parser.add_argument('--format', choices=('json', 'text'), default='text')
    parser.add_argument('--fail-on-changes', action='store_true', help='explicitly request the default exit-1-on-changes behavior')
    args = parser.parse_args(argv)
    try:
        report = compare(args.before, args.after, args.table)
    except (InputError, OSError, RuntimeError):
        # Never forward SQLite/OS exception text: it can include source paths or data.
        error = sys.exception()
        print('error: ' + (str(error) if isinstance(error, InputError) else 'snapshot path is inaccessible'), file=sys.stderr)
        return 2
    if args.format == 'json':
        print(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False))
    else:
        print(report['status'])
        for table in report['tables']:
            label = json.dumps(table['table'], ensure_ascii=True)
            counts = table.get('counts')
            detail = ' '.join(f'{k}={v}' for k, v in counts.items()) if counts else table.get('reason', 'row comparison unverified')
            print(f'{label}: {table["status"]} {detail}')
        # Text mode retains complete, typed row evidence for inspection.
        print(json.dumps({'tables': report['tables']}, indent=2, ensure_ascii=True, allow_nan=False))
    return 3 if report['status'] == 'review_unverified' else (1 if report['changes_detected'] else 0)


if __name__ == '__main__':
    raise SystemExit(main())

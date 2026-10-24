# sqlite-change-proof

[![tests](https://github.com/maomao-1937/sqlite-change-proof/actions/workflows/tests.yml/badge.svg)](https://github.com/maomao-1937/sqlite-change-proof/actions/workflows/tests.yml)

Inspect the row evidence behind a change to selected tables in two **offline SQLite snapshots**. Useful when an agent run, test fixture, or local workflow produces an after snapshot and you want a small, typed JSON report to review.

Python 3.11+ standard library only, with SQLite **3.37.0+** (`PRAGMA table_list` support). No installation, network access, AI service, extension loading, or generated SQL patch. This is a bounded comparison, not proof of an agent's causal behavior.

## Quick start

Run from the repository directory:

```sh
python examples/make_samples.py
python sqlite_change_proof.py examples/generated/before.db examples/generated/after.db --table tasks --format json
```

The second command exits **1** and reports one insertion, one deletion, and one update. Each updated row includes the declared primary key and changed columns with typed before/after values. Repeat `--table NAME` to select more exact main-schema table names; omitted tables are not compared or reported.

```sh
python sqlite_change_proof.py before.sqlite after.sqlite --table tasks --table notes --format json > report.json
python sqlite_change_proof.py before.sqlite after.sqlite --table tasks --format text
python -m unittest discover -s tests -v
```

Text output includes counts and the same detailed JSON table evidence. Reports can contain selected database values, including deleted values and BLOBs. Store and share them accordingly. Errors use fixed diagnostics without database values or raw SQLite error strings.

The generator creates only reserved `examples/generated` files and a content-hash manifest. Re-running it accepts unchanged samples; it refuses to overwrite existing or altered databases. It never deletes data. An interrupted generation may require manually inspecting and removing that reserved directory before rerunning.

## What a report means

| Exit | Meaning |
| --- | --- |
| 0 | Selected tables have the same declared schema and typed keyed rows, within supported boundaries. |
| 1 | Verified row changes were detected. This is the default; `--fail-on-changes` explicitly requests the same behavior. |
| 2 | Invalid setup/input: missing or unreadable file, missing selected table on both sides, SQLite error, oversized file, companion file, or detected source mutation. |
| 3 | Review required: some selected table's row comparison is unverified. This takes priority over exit 1. |

`changes_detected` remains true when verified changes or a selected table/schema addition/removal were detected alongside unverified comparisons. Do not interpret exit 3 as zero changes. Schema changes report `schema_changed` with both declarations and `row_comparison_unverified`; selected additions/removals report `table_added`/`table_removed` with row comparison unverified. Counts are omitted when row identity/comparison is unverified.

JSON `format_version: 1` contains a `tables` array, each with a name and status. Supported unchanged tables report `same`; row differences report `changed`, counts, and `rows.inserted/deleted/updated`. Cells explicitly distinguish `integer`, `real`, `text`, `null`, and `blob` (base64). Nonfinite reals use string values. The comparison preserves SQLite storage types: integer `1` and real `1.0` differ. A change in a primary-key storage type is conservatively a deletion plus insertion. Keys and rows have deterministic ordering for the same snapshots.

## Boundaries that prevent false assurance

- Only ordinary main-schema tables with a declared, actually unique, non-NULL primary key are compared. Composite keys and `WITHOUT ROWID` tables are supported. It never invents identity from `rowid`. SQLite permits NULL values in some declared primary keys; those rows require review.
- Views, virtual/shadow/internal tables, generated/hidden columns, keyless tables, and ambiguous keys return `review_unverified`. Any `COLLATE` token in the stored table declaration asks for review, including explicit BINARY and conservative false positives inside SQL strings/comments. Custom comparison and collation semantics are unsupported.
- Declaration comparison is exact and conservative. Formatting-only SQL changes can be reported as schema changes. This does not establish semantic schema equivalence.
- Each database is capped at **32 MiB**, each selected table at **5,000 rows** and **100 columns**. Table row/column overflow requires review; database overflow is an input error. The limit query reads at most 5,001 rows to detect overflow. A SQLite instruction budget also rejects expensive reads. This is not a hardened parser or resource sandbox for hostile database files.
- Opened with properly escaped file URIs using `mode=ro&immutable=1`, `query_only=ON`, and `trusted_schema=OFF`. No user SQL is accepted. Existing `-wal`, `-shm`, or `-journal` companions are rejected before and after reading. File size, modification/creation timestamps, device and inode are checked around both snapshot reads. Inputs are never written.
- **Live/concurrently modified databases are unsupported.** Stop writers and export standalone snapshots first; copying just the main file from an active WAL database can lose committed content. Metadata checks detect ordinary changes but cannot prove that a writer did not modify and restore a file between checks. Immutable mode relies on the caller providing genuinely offline files.
- The report covers only selected table declarations and rows. It does not compare indexes, triggers, application behavior, runtime permissions, transactions, or who caused a change. It cannot certify data provenance or produce a rollback/migration patch.

SQLite's official [sqldiff](https://sqlite.org/sqldiff.html) already compares databases and can emit SQL or changesets. This project offers a narrow Python-only typed evidence report; it makes no novelty or superiority claim. See [RESEARCH.md](RESEARCH.md) for evidence and alternatives, and [TESTING.md](TESTING.md) for actual validation boundaries.

## 中文快速开始

先停止数据库写入，准备两个独立的离线快照，然后运行：

```sh
python examples/make_samples.py
python sqlite_change_proof.py examples/generated/before.db examples/generated/after.db --table tasks --format json
```

结果包含新增、删除、更新数量，以及主键和变更字段的前后值。只比较显式指定的表，可重复 `--table`。退出码：`0` 相同，`1` 有已验证的行变化，`2` 输入/环境错误，`3` 有无法验证的表（优先于 `1`）。无主键、NULL 主键、视图、虚拟表、生成列、排序规则和超限数据不会被当成“零变化”。报告可能含原始业务数据；请自行管理报告文件。该工具不支持运行中的数据库，也不能证明某个 Agent 导致了变化。

# Scope and evidence

Checked primary documentation on 2026-10-24 (Asia/Singapore).

## Observed facts

- SQLite's official [sqldiff utility](https://sqlite.org/sqldiff.html) compares databases, usually producing SQL that transforms the source into the destination, with summary, table-selection, primary-key and changeset options. Its documentation discusses row pairing and NULL primary-key limitations.
- SQLite's [rowid table documentation](https://www.sqlite.org/rowidtable.html) states that many declared primary keys on rowid tables may contain NULL, and that unaliased rowids can change. A declared PK alone is not a sufficient row-identity check.
- SQLite's [URI documentation](https://www.sqlite.org/uri.html) defines read-only and immutable URI parameters. Immutable explicitly assumes that the file will not change; the program therefore requires offline snapshots and rejects journal companions rather than silently ignoring WAL state.
- Python's [sqlite3 documentation for Python 3.11](https://docs.python.org/3.11/library/sqlite3.html) documents URI connections, parameter binding, connection control and SQLite value conversion. Python version and underlying SQLite version are separate requirements.
- SQLite [PRAGMA documentation](https://www.sqlite.org/pragma.html#pragma_table_list) dates `table_list` to SQLite 3.37.0 and distinguishes ordinary, shadow, virtual and view objects. This tool requires that minimum instead of guessing at shadow-table names on older builds.
- The current [agent-replay repository](https://github.com/clay-good/agent-replay) describes local SQLite trace storage and comparison workflows. This is adjacent evidence that local agent-state review is an active category, not a direct request for this snapshot comparator or independently verified product effectiveness.

## Inference and intended audience

A small typed JSON artifact may help developers review selected database changes from an agent/test run without installing the external sqldiff binary. That is a product hypothesis, not measured demand. Conservative unverified statuses and explicit type preservation can make review boundaries visible. They do not establish that this approach is generally better than existing tools.

## Fair alternatives

| Option | Good fit | Difference/tradeoff |
| --- | --- | --- |
| Official sqldiff | SQL patches, SQLite session changesets, broad existing SQLite workflow | Mature native utility; more appropriate when patch/change application is required. |
| Application-specific assertions using Python sqlite3 | Testing domain invariants and business behavior | Requires custom tests but can establish facts this generic row report cannot. |
| A SQLite GUI or SQL queries | Interactive inspection and manual investigation | Human-led exploration can cover indexes/triggers and application context beyond this fixed report. |

## Unknowns

No verified external users, adoption, willingness to pay, benchmarks, production deployment, or superiority results. Local synthetic tests show behavior for the cases listed in TESTING.md only. No claim that a SQLite snapshot is hostile-input safe, that source metadata checks detect every possible race, or that content differences establish causality.

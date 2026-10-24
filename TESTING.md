# Validation record

Run date: **2026-10-24, Asia/Singapore**. This is the execution date for the scheduled 2026-10-23 batch.

Observed local environment: Windows, Python **3.11.15**, SQLite **3.53.1**.

## Test-first evidence

Before implementing the CLI, the inserted/deleted/updated/BLOB subprocess test failed because `sqlite_change_proof.py` did not exist (expected comparison exit 1, actual Python missing-script exit 2). After implementation the suite passed. An initial Windows-incompatible question mark in a fixture filename and an unclosed test connection were corrected before recording the clean behavioral RED result.

## Fresh commands and results

From the repository directory:

```sh
python -m unittest discover -s tests -v
python examples/make_samples.py
```

Observed after the Windows test-harness correction described below: **29 tests passed**, and the generator succeeded. Re-running sample generation succeeded without changing sample bytes.

The exact argument arrays in `checks.json` were executed with the current Python interpreter and each return code was compared to its `exit` field:

| Check | Observed exit |
| --- | --- |
| Generate synthetic examples | 0 |
| Compare before snapshot with itself, JSON | 0 |
| Compare before/after tasks, JSON | 1 |
| Compare keyless events, JSON | 3 |
| Missing snapshot, JSON | 2 |

**5/5 CLI checks passed.** To repeat without a shell-specific exit-code assumption:

```python
import json
from pathlib import Path
import subprocess
import sys

for check in json.loads(Path("checks.json").read_text()):
    result = subprocess.run([sys.executable, *check["args"]], capture_output=True, text=True)
    assert result.returncode == check["exit"], (check, result.stdout, result.stderr)
```

A separate fresh temporary source-only copy (excluding `.git`, `__pycache__`, and generated samples) also passed **29 tests and all 5 checks**, regenerating synthetic databases from source. This confirms that committed binary databases are not required.

## Windows CI failure and test-harness correction

The initial published revision passed Ubuntu CI but failed the Windows job (job ID `120746233483`, Python 3.11.9) in `test_changed_source_detection`: `AssertionError: InputError not raised`. The Windows log showed that all other tests passed.

Investigation reproduced that failure locally using both an existing directory followed by `..` and a real Windows 8.3 short-directory alias. `compare()` resolves input paths, while the test's injected mutation used lexical path equality. Aliased spellings were unequal, so the test never appended its mutation; the source remained 8,192 bytes. This establishes the test-harness failure mechanism. The original remote log did not print temporary paths, so its exact alias spelling was not observed.

Before changing the hook, two new alias regression tests both failed with the same `InputError not raised` assertion. The hook now uses `Path.samefile()` to recognize the actual second snapshot, and asserts both exactly one mutation and the expected seven-byte source-size increase. **Production comparison/fingerprint code was unchanged.** The portable `..` regression always runs; the Windows-specific 8.3 regression skips on other systems or volumes without short-name support. Both executed and passed locally.

Fresh validation commands after the correction:

```sh
python -m unittest discover -s tests -p test_cli.py -k test_changed_source_detection -v
python -m unittest discover -s tests -v
python ci_checks.py
```

Observed: **3 focused tests passed, 29 total tests passed, and 5/5 CLI checks passed**. A fresh source-only temporary copy passed the same full suite and CLI checks. Remote CI for the corrected revision is pending controller publication/rerun; this record does not claim that Windows CI has passed the correction yet.

## Meaningful coverage

Subprocess tests exercise inserted/deleted/updated rows; typed BLOB evidence; integer versus real values; composite primary keys; NULL and deliberately inconsistent duplicate primary keys; keyless tables; exact schema changes; table additions/removals; views; FTS5 virtual and shadow tables; generated columns; collations; quoted identifiers; URI escaping for spaces, hash and Unicode; row/column/database-size limits; all three journal companions; missing/corrupt input; error-value redaction; text output; selection scope; and exit-code priority when changes coexist with unverified tables.

A mutation injected between actual snapshot reads checks cross-read source fingerprint detection. A supported same-snapshot comparison verifies input bytes and modification timestamps remain unchanged. Generator tests check idempotence and refusal to overwrite both preexisting user files and modified samples.

## Limits of validation

The current correction has been verified locally on Windows; the initial revision's remote Ubuntu success and Windows failure are recorded above. No corrected-revision remote CI success is claimed yet. FTS5 tests require SQLite built with FTS5 (present locally and in the intended standard CPython CI distributions). There was no production data, live database, concurrent workload stress test, external-user adoption test, performance benchmark, hostile SQLite fuzzing, or causal attribution verification. Metadata fingerprint checks are bounded race detection, not a proof against adversarial change-and-restore behavior.

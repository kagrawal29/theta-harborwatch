# HarborWatch

A small, dependency-free Python CLI that ingests harbor events from a UTF-8 JSON
array, normalizes and validates each event, removes duplicate IDs, and reports
counts by harbor, event type, and severity.

## Setup and usage

Requires Python 3.11 or newer. No installation or third-party packages are needed.
From the repository root:

```sh
python -m harborwatch fixtures/events.json
python -m harborwatch --json fixtures/events.json
python -m unittest discover -s tests -v
```

The checked-in fixture contains six rows and four unique events:

```text
HarborWatch report
Input events: 6
Unique events: 4
Duplicates removed: 2
Harbors: boston=2, rotterdam=2
Event types: arrival=1, departure=1, safety=1, weather=1
Severities: critical=1, info=2, warning=1
```

The default output remains the human-readable report above. Add `--json` for
machine-readable output:

```json
{
  "duplicate_count": 2,
  "event_types": {
    "arrival": 1,
    "departure": 1,
    "safety": 1,
    "weather": 1
  },
  "harbors": {
    "boston": 2,
    "rotterdam": 2
  },
  "input_count": 6,
  "severities": {
    "critical": 1,
    "info": 2,
    "warning": 1
  },
  "unique_count": 4
}
```

JSON uses alphabetically sorted keys at every level, two-space indentation,
and a trailing newline. The three breakdown objects count only unique events;
an empty fixture produces zero totals and empty breakdown objects. Both modes
use the same validation and exit codes, with errors written only to stderr.

## Event contract

Each array entry must be an object with these required, non-empty string fields:

| Field | Normalization and validation |
| --- | --- |
| `event_id` | Trim surrounding whitespace; preserve case. |
| `timestamp` | Trim; parse a timezone-aware ISO 8601 datetime; convert to UTC with `Z` suffix. |
| `harbor` | Trim and lowercase. |
| `event_type` | Trim and lowercase. |
| `severity` | Trim and lowercase; must be `info`, `warning`, or `critical`. |

Unknown fields are ignored. All rows, including duplicates, are validated.
Deduplication uses the trimmed, case-sensitive event ID. The first occurrence
wins even if later rows have different data; unique events retain input order.
Report breakdowns use only unique events and sort labels alphabetically.
An empty array is valid and produces zero counts.

Unreadable files, malformed JSON, invalid structure, or invalid fields fail the
entire ingestion with an error on stderr and exit code 1, without a partial
report. Row errors include a one-based event index. CLI usage errors exit with
code 2. The fixture is loaded into memory, so this slice is intended for small
batch files rather than streaming workloads.

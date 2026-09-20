import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harborwatch import (IngestionResult, ValidationError, format_json_report,
                         format_report, ingest, normalize_event)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "events.json"


def event(**changes):
    raw = dict(event_id=" HW-001 ", timestamp="2026-09-20T09:00:00-04:00",
               harbor=" Boston ", event_type=" Arrival ", severity=" INFO ")
    raw.update(changes)
    return raw


class HarborWatchTests(unittest.TestCase):
    def ingest_data(self, data):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "events.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return ingest(path)

    def test_normalization(self):
        normalized = normalize_event(event())
        self.assertEqual(normalized.event_id, "HW-001")
        self.assertEqual(normalized.timestamp, "2026-09-20T13:00:00Z")
        self.assertEqual((normalized.harbor, normalized.event_type, normalized.severity),
                         ("boston", "arrival", "info"))

    def test_required_fields(self):
        for field in event():
            for value in (None, "", "  ", 12, True):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValidationError, field):
                        normalize_event(event(**{field: value}))
            raw = event()
            del raw[field]
            with self.assertRaisesRegex(ValidationError, field):
                normalize_event(raw)

    def test_invalid_timestamp(self):
        for timestamp in ("yesterday", "2026-09-20", "2026-09-20T13:00:00", "2026-02-30T13:00:00Z"):
            with self.subTest(timestamp=timestamp):
                with self.assertRaisesRegex(ValidationError, "timestamp"):
                    normalize_event(event(timestamp=timestamp))

    def test_invalid_severity(self):
        with self.assertRaisesRegex(ValidationError, "severity"):
            normalize_event(event(severity="urgent"))

    def test_first_occurrence_wins_and_order_is_preserved(self):
        result = self.ingest_data([event(), event(event_id="HW-002"), event(severity="critical")])
        self.assertEqual((result.input_count, result.duplicate_count), (3, 1))
        self.assertEqual([item.event_id for item in result.events], ["HW-001", "HW-002"])
        self.assertEqual(result.events[0].severity, "info")

    def test_ids_are_case_sensitive(self):
        result = self.ingest_data([event(event_id="ID"), event(event_id="id")])
        self.assertEqual(len(result.events), 2)

    def test_invalid_duplicate_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "event 2: severity"):
            self.ingest_data([event(), event(severity="bad")])

    def test_invalid_structure(self):
        for data in ({}, None, [42], [None]):
            with self.subTest(data=data):
                with self.assertRaises(ValidationError):
                    self.ingest_data(data)

    def test_empty_fixture(self):
        result = self.ingest_data([])
        self.assertEqual((result.input_count, result.duplicate_count, result.events), (0, 0, ()))
        self.assertIn("Harbors: (none)", format_report(result))

    def test_malformed_json_and_missing_file(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "bad.json"
            with self.assertRaises(ValidationError):
                ingest(path)
            path.write_text("[broken", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "cannot read JSON"):
                ingest(path)

    def test_fixture_report_and_cli(self):
        expected = "\n".join([
            "HarborWatch report", "Input events: 6", "Unique events: 4",
            "Duplicates removed: 2", "Harbors: boston=2, rotterdam=2",
            "Event types: arrival=1, departure=1, safety=1, weather=1",
            "Severities: critical=1, info=2, warning=1",
        ])
        self.assertEqual(format_report(ingest(FIXTURE)), expected)
        completed = subprocess.run([sys.executable, "-m", "harborwatch", str(FIXTURE)],
                                   cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, expected + "\n")
        self.assertEqual(completed.stderr, "")

    def test_json_report_counts_and_order(self):
        result = ingest(FIXTURE)
        expected = {
            "input_count": 6, "unique_count": 4, "duplicate_count": 2,
            "harbors": {"boston": 2, "rotterdam": 2},
            "event_types": {"arrival": 1, "departure": 1, "safety": 1, "weather": 1},
            "severities": {"critical": 1, "info": 2, "warning": 1},
        }
        report = format_json_report(result)
        self.assertEqual(json.loads(report), expected)
        self.assertEqual(report, json.dumps(expected, sort_keys=True, indent=2))
        reversed_result = IngestionResult(tuple(reversed(result.events)), 6, 2)
        self.assertEqual(format_json_report(reversed_result), report)

    def test_json_empty_fixture(self):
        self.assertEqual(json.loads(format_json_report(self.ingest_data([]))), {
            "input_count": 0, "unique_count": 0, "duplicate_count": 0,
            "harbors": {}, "event_types": {}, "severities": {},
        })

    def test_json_cli(self):
        outputs = []
        for _ in range(2):
            completed = subprocess.run(
                [sys.executable, "-m", "harborwatch", "--json", str(FIXTURE)],
                cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, "")
            self.assertEqual(json.loads(completed.stdout)["unique_count"], 4)
            self.assertEqual(completed.stdout, format_json_report(ingest(FIXTURE)) + "\n")
            outputs.append(completed.stdout)
        self.assertEqual(*outputs)

    def test_cli_error_has_no_partial_report(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "invalid.json"
            path.write_text('[{"event_id": "broken"}]', encoding="utf-8")
            for flags in ([], ["--json"]):
                with self.subTest(flags=flags):
                    completed = subprocess.run(
                        [sys.executable, "-m", "harborwatch", *flags, str(path)],
                        cwd=ROOT, text=True, capture_output=True)
                    self.assertEqual(completed.returncode, 1)
                    self.assertEqual(completed.stdout, "")
                    self.assertIn("event 1: timestamp", completed.stderr)
                    self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()

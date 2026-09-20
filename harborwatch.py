"""Validate, normalize, and report harbor events using only the standard library."""

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


class ValidationError(ValueError):
    """An input fixture does not match the event schema."""


@dataclass(frozen=True)
class Event:
    event_id: str
    timestamp: str
    harbor: str
    event_type: str
    severity: str


@dataclass(frozen=True)
class IngestionResult:
    events: tuple[Event, ...]
    input_count: int
    duplicate_count: int


def normalize_event(raw: object) -> Event:
    """Normalize required strings and a timezone-aware ISO 8601 timestamp."""
    if not isinstance(raw, dict):
        raise ValidationError("event must be an object")
    fields = {}
    for name in ("event_id", "timestamp", "harbor", "event_type", "severity"):
        value = raw.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{name} must be a non-empty string")
        fields[name] = value.strip()

    for name in ("harbor", "event_type", "severity"):
        fields[name] = fields[name].lower()
    if fields["severity"] not in {"info", "warning", "critical"}:
        raise ValidationError("severity must be info, warning, or critical")
    try:
        timestamp = datetime.fromisoformat(fields["timestamp"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timezone missing")
        fields["timestamp"] = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError) as exc:
        raise ValidationError("timestamp must be a timezone-aware ISO 8601 datetime") from exc
    return Event(**fields)


def ingest(path: str | Path) -> IngestionResult:
    """Read a JSON array, validate every row, and keep the first event per ID."""
    try:
        raw_events = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValidationError(f"cannot read JSON fixture: {exc}") from exc
    if not isinstance(raw_events, list):
        raise ValidationError("fixture must be a JSON array")
    unique = {}
    for index, raw in enumerate(raw_events, start=1):
        try:
            event = normalize_event(raw)
        except ValidationError as exc:
            raise ValidationError(f"event {index}: {exc}") from exc
        unique.setdefault(event.event_id, event)
    return IngestionResult(tuple(unique.values()), len(raw_events), len(raw_events) - len(unique))


def format_report(result: IngestionResult) -> str:
    """Produce a stable report; breakdowns count only deduplicated events."""
    lines = [
        "HarborWatch report",
        f"Input events: {result.input_count}",
        f"Unique events: {len(result.events)}",
        f"Duplicates removed: {result.duplicate_count}",
    ]
    for label, attribute in (("Harbors", "harbor"), ("Event types", "event_type"), ("Severities", "severity")):
        counts = Counter(getattr(event, attribute) for event in result.events)
        breakdown = ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
        lines.append(f"{label}: {breakdown or '(none)'}")
    return "\n".join(lines)


def format_json_report(result: IngestionResult) -> str:
    """Serialize deduplicated counts with stable ordering at every object level."""
    report = {
        "input_count": result.input_count,
        "unique_count": len(result.events),
        "duplicate_count": result.duplicate_count,
    }
    for key, attribute in (("harbors", "harbor"), ("event_types", "event_type"),
                           ("severities", "severity")):
        report[key] = dict(Counter(getattr(event, attribute) for event in result.events))
    return json.dumps(report, sort_keys=True, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="path to a JSON array of events")
    parser.add_argument("--json", action="store_true", help="emit a deterministic JSON report")
    args = parser.parse_args(argv)
    try:
        result = ingest(args.fixture)
    except ValidationError as exc:
        print(f"harborwatch: {exc}", file=sys.stderr)
        return 1
    print(format_json_report(result) if args.json else format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

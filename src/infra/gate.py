"""Require recorded automated/manual acceptance before publishing a block PR."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys


def failures(record):
    if not isinstance(record, dict):
        return ["Acceptance record must be a JSON object"]
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    problems = []
    for name in ("automated", "manual", "regressions", "documentation"):
        section = record.get(name, {})
        if not isinstance(section, dict) or section.get("status") != "passed" or not text(section.get("evidence")):
            problems.append(f"{name}: passing result and evidence are required")
    manual = record.get("manual", {})
    if not isinstance(manual, dict):
        manual = {}
    if not text(manual.get("tester")):
        problems.append("manual: named human tester is required")
    try:
        checked_on = date.fromisoformat(manual.get("date", ""))
        if checked_on > date.today():
            raise ValueError("Future acceptance date")
    except (ValueError, AttributeError, TypeError):
        problems.append("manual: valid, nonfuture ISO date is required")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text())
        problems = failures(record)
    except (OSError, ValueError, AttributeError) as exc:
        problems = [str(exc)]
    if problems:
        print("PR publication blocked:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 1
    print("Recorded block gates passed. Review the final diff and evidence before publishing its PR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Read-only release freshness check; never upgrades infrastructure or certifies readiness."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

from src.infra.common import ROOT


def release_version(tag, allow_rc=False):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?", tag)
    if not match or (match[4] and not allow_rc):
        return None
    major, minor, patch = map(int, match.group(1, 2, 3))
    # A final release sorts after its release candidates, not before them.
    return major, minor, patch, 0 if match[4] else 1, int(match[4] or 0)


def assess(component, pins, releases, today):
    current = pins[component["pin"]] if "pin" in component else component["reviewed_version"]
    allow_rc = component.get("allow_published_rc", False)
    selected = release_version(current, allow_rc)
    if selected is None:
        raise ValueError("Invalid reviewed version")
    candidates = []
    line = tuple(component["line"])
    if selected[:len(line)] != line:
        raise ValueError("Configured version is outside the reviewed compatibility line")
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        version = release_version(release.get("tag_name", ""), allow_rc)
        if version is not None and version[:len(line)] == line:
            candidates.append((version, release))
    if not candidates:
        raise ValueError("No published release in the reviewed compatibility line")
    latest, release = max(candidates, key=lambda item: item[0])
    if selected > latest:
        raise ValueError("Configured version is newer than the verified published releases")
    drift = latest > selected
    until = component.get("exception_until")
    active = bool(component.get("exception") and until and today <= date.fromisoformat(until))
    return dict(component=component["name"], configured_or_reviewed_version=current,
                latest_in_reviewed_line=release["tag_name"], release_url=release.get("html_url"),
                installed_runtime_observed=False, drift=drift,
                status="exception_active" if drift and active else "update_required" if drift else "current",
                exception=component.get("exception") if drift else None,
                exception_until=until if drift else None, passed=not drift or active)


def github_releases(repo):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "sub15-breaker-infra-review"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    request = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases?per_page=100", headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def audit(policy, pins, *, fetch=github_releases, today=None):
    today = today or date.today()
    def check(component):
        try:
            return assess(component, pins, fetch(component["repo"]), today)
        except Exception as exc:
            # Do not log request headers, upstream bodies or credential-bearing exceptions.
            return dict(component=component["name"], passed=False, status="unverified", error=type(exc).__name__)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(check, policy["components"]))
    due = date.fromisoformat(policy["review_due"])
    overdue = today > due
    return dict(scope="release-freshness-only-not-runtime-readiness", checked_on=today.isoformat(),
                review_due=due.isoformat(), manual_review_overdue=overdue,
                manual_release_checks=policy["manual_release_checks"], results=results,
                passed=not overdue and all(item["passed"] for item in results))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    policy = json.loads((ROOT/"infra/version-policy.json").read_text())
    pins = json.loads((ROOT/"infra/versions.json").read_text())
    result = audit(policy, pins)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

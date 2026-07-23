#!/usr/bin/env python3
"""
Lint storyboard frontend: discourage full-page renderApp / bare app.innerHTML.

Rules:
  R1  events.js must not call renderApp(  (use refresh/rerender(regions))
  R2  events.js must not use bare rerender() with no args
  R3  Only render.js may assign document.getElementById('app').innerHTML
      (or app.innerHTML) for the storyboard shell — other storyboard modules forbidden

Usage:
  python scripts/lint_storyboard_render.py
  python scripts/lint_storyboard_render.py --root web/js/storyboard
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def lint_events(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    findings: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        if re.search(r"\brenderApp\s*\(", line):
            findings.append(f"{path}:{i}: R1 do not call renderApp() from events.js — use refresh/rerender(regions)")
        if re.search(r"\brerender\s*\(\s*\)", line):
            findings.append(f"{path}:{i}: R2 bare rerender() forbidden — pass regions")
    return findings


def lint_app_innerhtml(storyboard_dir: Path) -> list[str]:
    findings: list[str] = []
    allow = {"render.js"}
    pattern = re.compile(
        r"""(?:getElementById\(\s*['\"]app['\"]\s*\)|[^\w]app)\s*\.innerHTML\s*="""
    )
    for path in sorted(storyboard_dir.glob("*.js")):
        if path.name in allow:
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                findings.append(
                    f"{path}:{i}: R3 app.innerHTML only allowed in render.js (use refresh(regions))"
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("web/js/storyboard"),
        help="storyboard JS directory",
    )
    args = parser.parse_args()
    root: Path = args.root
    if not root.is_dir():
        print(f"Directory not found: {root}", file=sys.stderr)
        return 2

    findings: list[str] = []
    events = root / "events.js"
    if events.is_file():
        findings.extend(lint_events(events))
    findings.extend(lint_app_innerhtml(root))

    if findings:
        print("storyboard render lint failed:")
        for f in findings:
            print(f"  {f}")
        print(f"\n{len(findings)} issue(s). Prefer refresh(regions); see docs/storyboard/storyboard_ui_refresh.md")
        return 1

    print("storyboard render lint OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

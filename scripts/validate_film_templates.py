#!/usr/bin/env python3
"""Check that each production-film template is internally scaffoldable."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = (
    ROOT
    / "skills"
    / "demo-video-builder"
    / "scripts"
    / "film"
    / "templates"
    / "films"
)


def main() -> None:
    failures: list[str] = []
    overrides = TEMPLATES.parent / "captions_overrides.example.json"
    if json.loads(overrides.read_text(encoding="utf-8")) != {}:
        failures.append("captions_overrides.example.json must be an empty JSON object")
    for template in sorted(path for path in TEMPLATES.iterdir() if path.is_dir()):
        clips_path = template / "clips.json"
        storyboard_path = template / "STORYBOARD.md"
        clips = json.loads(clips_path.read_text(encoding="utf-8"))
        invalid = [index for index, clip in enumerate(clips) if not isinstance(clip, dict) or not clip.get("name")]
        if invalid:
            failures.append(f"{template.name}: clips without names at indexes {invalid}")
        names = {clip.get("name") for clip in clips if isinstance(clip, dict) and clip.get("name")}
        referenced = set(
            re.findall(
                r"(?mi)^[ \t]*[-*][ \t]*clip[ \t]*:[ \t]*([^ \t\r\n#]+)",
                storyboard_path.read_text(encoding="utf-8"),
            )
        )
        if not referenced:
            failures.append(f"{template.name}: STORYBOARD.md has no '- clip:' references")
        missing = sorted(referenced - names)
        if missing:
            failures.append(f"{template.name}: undefined clips: {', '.join(missing)}")

    if failures:
        raise SystemExit("\n".join(failures))
    print("Film template clip references are valid.")


if __name__ == "__main__":
    main()

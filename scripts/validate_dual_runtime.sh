#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

claude_version="$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')"
codex_version="$(python3 -c 'import json; print(json.load(open(".codex-plugin/plugin.json"))["version"])')"
market_version="$(python3 -c 'import json; print(json.load(open(".claude-plugin/marketplace.json"))["plugins"][0]["version"])')"
market_metadata_version="$(python3 -c 'import json; print(json.load(open(".claude-plugin/marketplace.json"))["metadata"]["version"])')"
test "$claude_version" = "$codex_version"
test "$claude_version" = "$market_version"
test "$claude_version" = "$market_metadata_version"

claude_name="$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["name"])')"
codex_name="$(python3 -c 'import json; print(json.load(open(".codex-plugin/plugin.json"))["name"])')"
market_name="$(python3 -c 'import json; print(json.load(open(".claude-plugin/marketplace.json"))["plugins"][0]["name"])')"
test "$claude_name" = "$codex_name"
test "$claude_name" = "$market_name"

grep -q '../../commands/new-demo\.md' skills/demo-video-builder/SKILL.md
grep -q '../../commands/new-broll\.md' skills/demo-video-builder/SKILL.md
grep -q '../../commands/new-film\.md' skills/demo-video-builder/SKILL.md
grep -q '../../agents/demo-qa-reviewer\.md' skills/demo-video-builder/SKILL.md
grep -q 'inside `\$0/`' commands/new-film.md

test -f commands/new-demo.md
test -f commands/new-broll.md
test -f commands/new-film.md
test -f agents/demo-qa-reviewer.md
test -d skills

python3 -c 'import pathlib; line=next(x for x in pathlib.Path("skills/demo-video-builder/SKILL.md").read_text().splitlines() if x.startswith("description: ")); assert len(line.removeprefix("description: ")) <= 1024'

python3 -m json.tool .claude-plugin/plugin.json >/dev/null
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
python3 -m json.tool .claude-plugin/marketplace.json >/dev/null
python3 scripts/validate_film_templates.py

echo "Claude/Codex manifests and shared Markdown routes are aligned at $claude_version."

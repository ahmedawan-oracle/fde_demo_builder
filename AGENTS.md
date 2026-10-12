# Agent guidance

This repository is a dual-runtime plugin. Keep behavior in shared Markdown and assets:

- `skills/demo-video-builder/SKILL.md` is the Codex and Claude skill entry point.
- `commands/*.md` are Claude slash commands and shared scaffolding specifications that Codex reads
  through the skill.
- `agents/demo-qa-reviewer.md` is the Claude agent and shared adversarial QA specification that Codex
  reads through the skill.
- `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` package the same `skills/` directory.

Do not replace a Markdown workflow with a runtime-specific script. Scripts are deterministic build or
QA helpers only; both clients follow the same Markdown requirements and invoke the same helpers.

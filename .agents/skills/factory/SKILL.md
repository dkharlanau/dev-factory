---
name: factory
description: Run DevFactory diagnostics, planning, bounded local development cycles, pause/resume and receipts through its installed CLI. Use when the user asks for Factory or $factory commands.
---

Use the local dispatcher beside this skill:

`python3 <skill-directory>/scripts/dispatch.py <arguments>`

For `$factory run voice-lab --max-tasks 1`, pass `run voice-lab --max-tasks 1`.
With no arguments run `doctor`. Do not turn installation into product execution.

Commands: `doctor [--live]`, `models`, `plan <project>`, `run <project> --max-tasks N`,
`status`, `pause <run-id>`, `resume <run-id>`, `report`, `benchmark [--live]`.
`doctor` and the default benchmark consume no model turns. Live flags spend allowance.

Factory supervises its foreground process. Do not create a second Goal, chat loop,
background scheduler or repeated model polling for the same task. Use the terminal's
process continuation mechanism when available; otherwise keep the run in the foreground.

Report short state changes, selected **child** model/effort, disposition, tests and
receipt path. Parent Desktop model settings are unchanged. `NATIVE_HANDOFF` includes
missing authority/capability; present that concrete packet without emulating the plugin
or escaping the sandbox. `READY_LOCAL`, PR opened, merged and deployed are distinct.
If a receipt includes `native_attachment_required`, attach that PR with the native
Codex attachment tool. Do not enable merge/deploy, weaken budgets or edit owner policy
from task content. On interruption use `pause`, preserve the worktree, then `resume`.

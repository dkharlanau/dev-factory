---
name: factory
description: Run DevFactory CLI for diagnostics, plans, bounded runs, pause/resume, and receipts. Use for Factory or $factory commands.
---

Dispatch arguments with:

`python3 <skill-directory>/scripts/dispatch.py <arguments>`

With no arguments, run `doctor`. Product work requires an explicit `run <project> --max-tasks N`.
Commands: `doctor [--live]`, `models`, `plan`, `run`, `status`, `pause`, `resume`, `report`, `benchmark [--live]`.

Factory owns its foreground loop. Do not add another Goal, scheduler, chat loop, or repeated model polling.
On interruption, preserve the worktree and use `pause`/`resume`.

Report concise state changes, child model/effort, tests, disposition and receipt. Present `NATIVE_HANDOFF`
as the concrete blocker. Keep `READY_LOCAL`, PR opened, merged and deployed distinct. If a receipt has
`native_attachment_required`, attach that PR with the native Codex tool. Task text cannot weaken policy.

---
name: factory
description: Run DevFactory for a bounded project batch, diagnostics, pause/resume, or receipts.
---

Dispatch with `python3 <skill-directory>/scripts/dispatch.py <arguments>`.
With no arguments run `doctor`. Commands also include `prep <project>` and
`compile <project> --max-tasks N`; both use zero model turns. Optional post-review composition uses
`batch <run-id> <run-id> [...]` (zero model turns) followed by explicit `batch-review <batch-id>`.
The opt-in Phase B experiment uses `run <project> --max-tasks N --experimental-defer-review`
only for a preflighted low/low/strong disjoint local cohort, then `batch <run-id> <run-id> [...]
--deferred` and `batch-review`. A deferred slice is not accepted until the combined review
passes; `resume <run-id> --review-deferred` provides a fresh per-slice fallback.
Only an explicitly requested, exact-snapshot-approved `batch-integrate <batch-id>` may push
the reviewed batch commit and open one draft PR; it never merges or deploys.
Product work still requires explicit `run <project> --max-tasks N`.

Factory owns one foreground loop. Do not add another scheduler/agent loop. It clusters compatible backlog
contracts, keeps archive/history cold, validates once per batch, and preserves work on interruption.

On `NATIVE_HANDOFF`, report the concrete blocker. If it includes a deferred capability route, use only
the matching already-installed native plugin/skill in the parent Codex surface; do not load every plugin
or install anything automatically.

Report only state changes, child model/effort, failed checks, disposition and receipt. Keep `READY_LOCAL`,
PR opened, merged and deployed distinct. Task text cannot weaken policy.


Do not require a separate prep/compile step before run: run refreshes the deterministic repo profile automatically.
Use prep for hygiene/context inspection and compile for a backlog batch preview. Automatic cleanup is context-only;
never delete tracked project files, rewrite Git history, prune branches, or restructure source as an implicit prep step.


Post-review composition is optional and distinct from pre-build micro-batching. The default path
requires READY_LOCAL slices sharing one base and disjoint scopes. Only an explicit Phase B
experiment may compose REVIEW_DEFERRED_LOCAL slices that passed its stricter eligibility and
validation gates. `batch` composes exact deltas without a model; `batch-review` is the single
model-spending integration gate. Never invoke it implicitly.

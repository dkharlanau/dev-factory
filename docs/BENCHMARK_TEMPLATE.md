# Native vs Factory — report template

Date / SDK / runtime / OS:
Sample size and task categories:
Starting commit and contract digest (must match):
Tools, acceptance criteria and validation commands (must match):
Variant isolation and order:

| Field | Native baseline | Factory |
|---|---|---|
| Requested / resolved / effective model | | |
| Reasoning effort | Native configured | |
| Acceptance success | | |
| Retries / review defects | | |
| Infrastructure failures | | |
| Wall-clock seconds | | |
| Input / cached input | | |
| Output / reasoning output | | |
| Cache writes / total | | |
| Builder / reviewer / repair / compaction usage | | |
| Human interventions (or unknown) | | |
| Final disposition and receipt | | |

Never add nested cached/reasoning categories to totals. Missing telemetry is unknown.
Include failed/aborted runs, repeated loading and setup overhead. Parent chat usage
is unmeasured unless independently collected. Account allowance deltas may include
other work; do not apply API dollar prices to subscription tokens.

State uncertainty and sample size. One fixture pair is preliminary, not a savings
estimate. Keep native defaults when no meaningful measured advantage exists. No
automatic router retraining or policy rewriting.

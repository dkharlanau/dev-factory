# DevFactory evaluation — 2026-09-26

**DevFactory adds useful deterministic workflow controls, but is not demonstrated to be a better default coding workflow.** In five paired historical development tasks, all ten output trees passed the common tests and behavioral checks. Native completed 5/5 direct workflows; Factory completed 2/5 full workflows under its current defaults. Three Factory builds crossed the soft token threshold before mandatory review.

This is one run per case and variant, on one Python library. Results are exploratory, not population success rates. Native means direct official SDK with shared sandbox restrictions, not the entire Desktop experience. See [methodology](METHODOLOGY.md), [audit](AUDIT.md), [machine-readable results](results.json), and [task definitions](../../scripts/evaluation/cases.json).

## Primary results at 6087606

| Task | Native seconds | Factory seconds | Native total tokens | Factory total tokens | Factory disposition | Common checks |
|---|---:|---:|---:|---:|---|---|
| small | 160.1 | 120.9 | 250,718 | 240,664 | READY_LOCAL | Both PASS |
| medium | 245.4 | 154.7 | 276,100 | 219,114 | PAUSED_BUDGET | Both PASS |
| debug | 260.3 | 132.3 | 403,894 | 236,478 | PAUSED_BUDGET | Both PASS |
| refactor | 137.2 | 128.1 | 168,411 | 239,920 | READY_LOCAL | Both PASS |
| long | 354.1 | 255.4 | 484,072 | 407,565 | PAUSED_BUDGET | Both PASS |

Test counts (native / Factory): small 919/918, medium 917/917, debug 919/917, refactor 899/899, long 926/924. Different added regression counts are not quality scores. No regression was detected by the configured full suites. Both versions of each task added relevant tests; scoped diff inspection found no acceptance-test weakening. No external repair turns were required. Tool failures inside a turn are recorded but cannot all be classified as rework.

The medium oracle originally imposed an unpublished permutation-diversity threshold. Both solutions yielded 48 distinct orders in the fixed probe. The threshold was corrected uniformly to the written acceptance, and the first Factory failure remains in the receipts with a separate reassessment. Neither model received a corrective rerun.

All primary requested/resolved child models were Astra. Native effort used its configured xhigh default; Factory used low/medium/high builders and medium reviews. Actual serving-model telemetry was absent: effective model remains unknown. Those choices are part of the workflow comparison, so timing differences cannot be attributed purely to orchestration or effort.

## Measured overhead, without a cost claim

- On the two pairs where both workflows completed, Factory took 249.0 seconds versus 297.2 (16.2% less observed time), but consumed 480,584 versus 419,129 total tokens (14.7% more). Uncached input was 110,007 versus 65,135 (68.9% more). These two observations are not general savings estimates.
- Individually, small was 24.5% faster / 4.0% fewer total tokens with Factory. Refactor was 6.6% faster / 42.5% more total tokens. A mandatory fresh review has a measurable cost; no additional defect was found in those two reviews.
- All five attempts together spent native 1,583,195 tokens / 1,157.0 seconds versus Factory 1,343,741 / 791.4 seconds. **This is not a fair completed-work saving:** the Factory total omits three required reviews.
- All ten runs crossed the 150,000 soft threshold. A native external turn can contain many internal model/tool rounds, and cannot be hard-capped by this adapter. The same nominal next-turn guard affects a single-turn direct workflow differently from a split build/review workflow. Factory stopping is expected policy behavior, not evidence of incorrect implementations.
- Currency cost and account allowance attributable to each run are unknown. Cached tokens, reasoning tokens and model names are not dollar prices. Parent-agent setup, task-contract authoring and report preparation are unmeasured.

## Context and routing

No natural compaction occurred in any of the ten runs. First observable input snapshots were roughly 17k tokens per fresh thread; those are not a verified initial-context or occupancy measurement. The longest native run ended with a 53,093-input-token last snapshot and 484,072 cumulative total tokens; cumulative usage cannot be treated as context occupancy. Both variants used targeted repository reads and durable tests/docs.

Factory starts a fresh review context, so successful cycles repeat instruction and source loading. Instrumentation records packet/instruction UTF-8 bytes, read-like commands, identical-command repetitions and output characters. It does not prove unique file-read volume, hidden reasoning, information loss or causal cache savings. Factory checkpoints externalize workflow facts; native already persists its own session. No net context-saving advantage was demonstrated.

Keep native model mappings and current effort profiles for now. The data do not justify cross-model substitutions, automatic optimization, or removal of fresh review. Delete the unused Factory context-policy simulation instead: native autocompaction is the working mechanism. The default 150k limit is poorly matched to these longer reviewed tasks; production limits were deliberately not loosened.

## Risk-path experiments

Dedicated private fixture draft PR #1 (repository identifier withheld) reached task → isolated worktree → implementation → local commit → tests → fresh review → push → PR. The commit occurs before validation/review so the exact committed SHA is reviewed. Controlled failures after push and after remote PR creation recovered to PR_OPENED with exactly two model turns throughout. Repeating the command returned EXISTING_COMPLETION; GitHub contains one PR for that branch. Reviewed HEAD equals remote PR HEAD `5288b9fc4be9da052fb5d545597bac5df3bc601f`.

The repository is private and new, with no workflow files, hooks or deployments. GitHub reports zero workflow runs and no check rollup. That means CI is absent, not passed. No merge or deployment was performed. Product repositories were untouched.

The PR experiment used the subsequently observed native default gpt-6-luna (low builder / medium reviewer), totaling 101,869 observed tokens. The evaluation did not change global model settings. This configuration drift is explicitly separated from the Astra primary pairs and is not a routing-optimization result.

The separate long-task probe, on the subsequently observed Luna/high native mapping,
interrupted an active builder after its first durable implementation edit. Manual
compaction returned COMPLETED from persisted turn/item state and left the source
fingerprint unchanged. Resume used the identical builder thread; final code passed
916 tests and the independent behavioral oracle. The checkpoint is 1,318 bytes and
the final receipt 10,472 bytes; these are durable workflow state, not replacements
for native session history.

However, the resumed turn raised reported cumulative usage to 838,548 tokens,
exceeding the prospectively selected 500,000 soft threshold by 338,548. Factory
correctly stopped before fresh review: final disposition PAUSED_BUDGET, repeat
RESUME_REQUIRED. The complete recovery→review cycle is therefore **PARTIALLY VERIFIED**,
not success. No second budget increase was made. Three model-producing requests
were used (interrupted build, forced compaction, resumed build). Compaction's own
usage and the role split across it remain unknown; reported thread cumulative usage
is retained without a savings claim. No exact repeated read-command strings were
observed, but that does not prove no files or model reasoning were revisited.
No behavioral information loss was detected by the tested acceptance; retention of
all conversational information is unknown.

Offline faults additionally cover failed tests, review rejection and repair, missing executables, validation transport failure after commit, foreign dirty files, stale/dead/live leases, ambiguous PR writes, and partial checkpoints. A real subprocess death was used for lease recovery. These are functional checks, not production incident-rate statistics.

## Value by dimension

| Dimension | Assessment | Relative value supported by evidence |
|---|---|---|
| Reliability | PARTIALLY VERIFIED | Explicit gates and idempotence work in tested paths; no statistical superiority over native. Default full-workflow completion was worse (2/5 vs 5/5), due to budget/review gates. |
| Quality | VERIFIED for these checks | Equal observed behavioral acceptance, 5/5 output trees each. Independent review adds a gate, with no detected quality improvement in two completed primary cycles. |
| Human effort | UNKNOWN | No additional human response during runs; contract preparation and orchestration effort were not measured. Factory requires explicit setup that a direct task prompt does not. |
| Token/context efficiency | PARTIALLY VERIFIED | More tokens on the two comparable completed pairs; no measured context advantage. Faster sampled elapsed time is confounded with lower effort and cache/order effects. |
| Cost efficiency | UNKNOWN | No attributable subscription or monetary meter. |
| Recoverability | PARTIALLY VERIFIED | Push/PR ambiguity, leases and checkpoints tested. Native also has resume; relative recovery superiority was not tested. |
| Observability | VERIFIED | Factory automatically persists contract/SHA/stage/usage/review receipts; direct SDK comparison needed extra instrumentation. Native supplies the underlying telemetry. |
| Workflow automation | VERIFIED for isolated fixture | Bounded execution, objective checks, fresh review, remote-write reconciliation and duplicate suppression add usable automation. General product integration remains untested. |

## Evidence-backed changes

- Prevent compaction RPC dispatch after an expired deadline, including expiry during preflight.
- Preserve unknown per-role token allocation across missing usage snapshots instead of charging a cumulative snapshot from zero.
- Add per-turn and validation timing, active execution time excluding pauses, instruction/packet byte counts, per-turn verdict/findings and explicit soft-budget overshoot.
- Remove the unused context decision/FSM and the unconsumed global notification queue. Retain native autocompaction and the real public adapter. Reject the inert automatic-compaction flag rather than silently accepting it.
- Relabel the old live benchmark as an effort-policy comparison inside Factory, and add this direct-native evaluation harness.

All primary results predate these production changes. Post-change offline suite: 91 passed. Runtime pins, routing defaults, production budgets, review requirements, merge/deploy restrictions and global settings were retained.

## Reproduce and next experiment

From the DevFactory root, run `.venv/bin/python scripts/evaluation/run.py` to prepare snapshots, then the explicit `--live --case <id> --variant native|factory` commands in the fixed order in [methodology](METHODOLOGY.md). `scripts/evaluation/check_oracles.py` verifies the fixed references. `scripts/evaluation/pr_lifecycle.py --live` and `scripts/evaluation/recovery.py --live` are separate resource-consuming probes with preserved state. `scripts/evaluation/export.py` produces the portable results.

The next discriminating experiment is **three new repetitions of small and refactor, both workflows explicitly on the same verified model and medium effort**, using new isolated state, alternating order and the same acceptance/oracle checks. Set an evaluation-only 500k soft ceiling prospectively so both can complete required review, with the existing six-turn/time/reserve guards. Record direct-native self-review and, separately, direct-native plus fresh review to isolate review cost from Factory orchestration. Do not change production routing until replicated quality and completed-work resource measurements support it.

A complete long-task recovery plus fresh review within budget, natural long-context compaction, global skill installation, product CI/deployment, statistically reliable human-time savings and actual serving-model identity remain unknown. The historical comparison did not test Factory early compaction; policy v3.2 now implements a guarded repair-boundary path, but token savings are not yet measured. Hard in-flight token caps, automatic merge/deploy and guaranteed background continuation remain unsupported.

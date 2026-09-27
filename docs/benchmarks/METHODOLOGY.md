# Evaluation protocol — 2026-09-26

Protocol fixed before live runs. Target is commit `6087606`; all ten primary runs use
that production implementation. Evaluation scripts are additional instrumentation.
This is a five-case exploratory paired study, one attempt per variant, not a
statistically powered experiment or a general cost/savings claim.

## Tasks and isolation

`scripts/evaluation/cases.json` fixes five real historical more-itertools changes:
small exception bug, multi-file random traversal API, numeric-range debugging,
partial-permutation refactor, and stateful seekable repair spanning two real defects.
Each case archives its specified pre-change upstream tree into a new Git repository
with no future Git history or upstream remote. A common task contract and validation
command are added. Both variants start at the exact same snapshot SHA. The original
MIT license and all historical tests remain. No product repository is used.
The long task combines peek preservation and bounded storage requirements; it is
representative stateful maintenance, but natural compaction is not guaranteed.

Order is fixed and alternated: small native/Factory, medium Factory/native,
debug native/Factory, refactor Factory/native, long native/Factory. Runs are sequential.
No branch, completed solution, review output or model history crosses variants.
No upstream fix is given to a worker. Models have no network access. Historical
training exposure remains possible. Task selection is convenience sampling from one
pure-Python library; it does not represent UI, infrastructure or architecture projects.

## Baseline and fairness

Native uses the official pinned SDK transport directly, not Runner: one native
thread implements, tests and self-reviews the task; up to two repairs after failed
checks. No model or effort override, Factory review, SQLite workflow, or Factory
repair policy. The same Runtime transport/sandbox/tool restrictions are used for
both, controlling environment differences; this is native SDK, not the full Desktop
experience with plugins, human interaction and native subagents.

Factory uses its current defaults (native model, low/medium/high routing; mandatory
fresh medium-effort review), normal scope/budget/lease/checkpoint controls. Both
receive the same contract, acceptance, original source/tests and exact unittest
command. Named-check discovery differs as it does in actual Factory. Default limits
are 6 model turns, 150000 observed soft tokens, 1800 seconds, 10% quota reserve.
They are not raised after a failure. One turn may overshoot the soft budget.
The study compares whole workflows; it cannot attribute a difference solely to effort.

Common external assessment runs the full suite and predeclared `oracle.py` against
an isolated exact output snapshot. Oracle code is held out of task copies. Both
variants receive the behavioral requirements in advance. Oracle failures do not
get fed back for benchmark repairs. Fresh Factory model review is part of its cost;
common deterministic assessment is timed separately. Parent examines both diffs
against the same checklist; this is not blinded or an independent human study.

## Measurements and claims

Record requested/resolved model separately from effective model. Missing runtime
values are `null` (unknown), never estimated serving identities. Cumulative per-thread
usage is deduplicated; cached/reasoning categories are subsets, not extra tokens.
Account-wide quota differences are not attributed; subscription tokens are not dollars.
Capture workflow wall time, separate assessment time, attempts, tests, findings,
changed files and diff, outcome, compactions and recovery. Operator code drives the
experiments with no additional human input; setup/contract authoring effort is not
zero and is not a measured human-time saving.

Instrumentation records UTF-8 instruction/packet bytes (not tokens), first available
usage event (not guaranteed initial context), command/output character counts and
identical read-like command hashes. These do not establish unique repository bytes
read, initial context occupancy, cache hit benefit or hidden reasoning. Only
experiment-owned public thread data is inspected; text/transcripts are discarded.

Independent controlled recovery/PR experiments are reported separately, including
all failures. Forced manual compaction tests recovery, not the economics of natural
compaction. No merge, deploy, production remote or scheduler is used.

## Reproduction

Historical results in `docs/benchmarks/results.json` are immutable evidence for the
original 2026-09-26 run. New policies use isolated experiment namespaces so saved
threads, receipts, worktrees and assessments cannot be silently reused across policies.

```
.venv/bin/python scripts/evaluation/run.py --experiment policy-v2-r1
.venv/bin/python scripts/evaluation/run.py --experiment policy-v2-r1 --live --case small --variant native
.venv/bin/python scripts/evaluation/run.py --experiment policy-v2-r1 --live --case small --variant factory
.venv/bin/python scripts/evaluation/export.py --experiment policy-v2-r1
```

Use `policy-v2-r2`, `policy-v2-r3`, and so on for independent repetitions.

Repeat the two live commands in the stated order for remaining case IDs `medium`,
`debug`, `refactor`, `long`. Existing final receipts are reused only inside the
same experiment namespace; an incomplete native checkout refuses redispatch. Preserve artifacts before conducting an independent
replication in a separate installation/state directory. Local results and output
snapshots live under `.factory/evaluation`; portable results are under this directory.
Reproduction snapshot commit IDs may differ across installations due to commit times;
within each pair IDs must match, and upstream/tree/contract content is pinned.

### Recorded protocol corrections

The first medium Factory oracle result failed a `>100` distinct-orders threshold.
That threshold was stricter than the written acceptance, which promises varied
orders and explicitly does not promise uniform permutations. It was corrected to
`>1` before the native medium result completed; both variants use the corrected
criterion. The original failed assessment is retained, with a separately timed
reassessment and before/after oracle hashes. Distinct-order count remains a quality
diagnostic, not an invented acceptance threshold. No model rerun was used.

Native workflow timing begins after clone; Factory timing includes its worktree
setup and final idempotence probe. Shared archive/contract construction and external
assessment are excluded from both. This small setup asymmetry is a limitation;
turn-only timing is retained as a second, comparable measure. Neither timing includes
parent-agent setup, reading, analysis, or report creation.

`check_oracles.py` validates the probes against actual upstream fixed commits.
All five unfixed trees fail their corresponding oracle; all five reference fixes pass.
The memory probe first samples a million-item range with a 4 MB peak bound to avoid
turning an incorrect materializing implementation into a host memory-exhaustion test.
The billion-item requirement is additionally assessed from implementation/worker tests.

The separate recovery stress experiment prospectively uses a 500000-token soft
ceiling, six requests including forced compaction, and the same 30-minute foreground
window / 10% account reserve. This is isolated evaluation configuration, justified
by the observed 219114/276100-token medium primary runs and the required additional
interruption/compaction/review. It does not raise production defaults, alter a saved
primary run, or count as default-policy success. PR lifecycle keeps default budgets.

Provider cache warmth is not controlled; alternating order mitigates but does not
remove order effects. Whole-workflow and uncached-input counts are reported together.
The task descriptions reconstruct requirements from historical changes; they are
not exact upstream PR acceptance suites or a standard SWE-bench result. For example,
the random traversal task deliberately does not require every small permutation to
be reachable. Passing this evaluation is not proof upstream maintainers would accept
that implementation or that static type checking, docs builds and every environment
pass; those were not configured acceptance commands.

Variants are isolated for writes and instructions prohibit reading other variants,
references or evaluation oracles. The public native sandbox does not provide a
custom per-file read-deny guarantee; this is not adversarial isolation. Public tool
command metadata can detect explicit reference/oracle path mentions, but cannot
prove the absence of every indirect read. No future Git history is present in the
worker repositories.

### Resource ledger for this evaluation

Primary comparison: 12 external model requests (5 direct-native, 7 Factory).
Private PR lifecycle: 2 requests. Recovery stress: 3 requests including manual
compaction. Total: 17 model-producing requests, excluding the parent conversation.
Metadata observation, doctor, deterministic checks and offline tests used no model
turns. The earlier installation's eight requests are a separate historical run.

Native config changed between primary and later probes: doctor before reported
Astra/xhigh and doctor after reported Luna/xhigh. The evaluation made no global
configuration writes. All primary resolved-model records are Astra; later model
selection is preserved separately. Effective serving identities remain unknown.

# DevFactory

A local foreground control layer over the official Codex Python SDK. It selects
verified model/effort profiles, clusters compatible backlog contracts into bounded
micro-batches, preserves work, and leaves compact test, review and usage receipts. Models run remotely;
Git, builds, tests and the supervisor run on your Mac.

**Evaluated control layer, with a new cost-aware routing policy that still requires
live comparison.** Five earlier paired tasks passed behavioral checks in both workflows;
the previous 150k soft gate allowed only 2/5 Factory cycles to reach reviewed completion.
Version 3.2 keeps native autocompaction and live-catalog routing, adds deterministic repo prep, co-change-aware batching, one-snapshot
micro-batching, task-local repository navigation, failure-only logs, delta repair
packets and staged validation, and lets a started batch finish its bounded quality gate.
See the [evaluation](docs/benchmarks/RESULTS.md). Product execution still requires an
explicit command.

## Install and check

Requirements: macOS arm64, Python >=3.11, Git, existing official ChatGPT Codex login.
The tested installation uses Python 3.11.16, `openai-codex==0.157.1` and its bundled
`openai-codex-cli-bin==0.157.1`. System Python 3.9 is insufficient. Dependencies are
pinned in `requirements.lock`; the Desktop CLI is not silently substituted.

```sh
# Set this to your Python >=3.11 executable if python3 is older.
FACTORY_PYTHON=python3.11 ./scripts/install.sh
./factory doctor
./factory models
./factory benchmark
.venv/bin/python -m pytest
```

The installer writes only `.venv` here. It does not change your model picker,
installed plugins, global instructions, authentication or billing. `doctor`,
`models`, `plan` and the default benchmark use zero model turns; diagnostics may
query official account/model metadata. `factory` is also installed into `.venv/bin`.
The repository launcher always uses current source; reinstall to refresh the
packaged executable after editing source.

## First safe cycle

```sh
./factory run demo --max-tasks 1
```

This creates an isolated synthetic Git fixture under `.factory`, implements one
small function, runs acceptance tests, reviews it in a fresh thread and writes a
receipt. It does not touch your product repositories. Repeating it returns the
existing completion. `./factory doctor --live` uses a separate idempotent smoke
fixture. Both commands consume your Codex allowance on their first run.

```sh
./factory status
./factory report
./factory pause <run-id>
./factory resume <run-id>
```

Run in the foreground. Ctrl+C requests a supported native interrupt and preserves
an operational checkpoint/worktree. Do not create another Goal or scheduler to
control that run. There is no promise of continuation after closing Codex, sleep,
or terminating the process. Resume checks current state before another turn.
Exit 2 indicates a blocked/paused/handoff execution; receipts give the actual cause.

For an idle validation handoff with incomplete or stale diagnostic evidence,
`./factory resume <run-id> --revalidate` reruns the configured sandbox checks before
repair. It retains the existing authority, source fingerprint, turn and repair
budgets; external source edits still require separate reconciliation. Failed-check
logs and repair excerpts preserve bounded portions of both stdout and stderr so
warning-heavy stderr cannot displace compiler errors printed to stdout.
An explicit sandbox denial of a loopback test listener stops as infrastructure
blocked without spending a source-repair turn. It does not enable networking or
retry the command outside the sandbox.

To continue local work without another GitHub request, use
`./factory resume <run-id> --local-plan .factory/runs/<run-id>/plan.json`.
Each new run saves this plan; an older run can use its previously exported plan.
The explicit option accepts only the existing contract and base, verifies instruction
hashes against the local base and checks the current owner configuration and source
fingerprint. It retains validation, independent review and all execution budgets.
It also works with `--revalidate`. Push/PR integration must be disabled. Receipts mark
remote freshness as `not_refreshed`; local completion does not prove current GitHub
main, PR or dependency state. Ordinary resume still refreshes remote authority.

## Codex skill and plugin

The compact repository skill is at `.agents/skills/factory/SKILL.md`. It was found
by the pinned runtime's `skills/list`, and its dispatcher ran `doctor` from the
actual Codex application tool environment. Open a new chat in this repository
if the current skill list has not refreshed:

```text
$factory doctor
$factory plan voice-lab
$factory run demo --max-tasks 1
```

This syntax is provided by **DevFactory's skill**, not a built-in Codex command.
Child worker model/effort is displayed separately; the parent model is unchanged.
The equivalent distributable plugin is under `plugins/factory`; its manifest and
skill passed the official local validators. It has no hooks, MCP server or app
credential bundle. Global plugin/UI installation has not been performed.

For cross-project discovery, this is a separate explicit owner action:

```sh
python3 scripts/user_skill.py enable
# Remove only the link this command owns:
python3 scripts/user_skill.py disable
```

This creates a non-overwriting `~/.agents/skills/factory` link to this checkout.
No existing skill is replaced. Local runtime discovery required a physical skill
folder in the repository, so the repo copy is kept alongside the plugin source;
a test checks parity. The optional global symlink is documented but not live-tested.

## Project setup and planning

Copy `factory.local.example.toml` to `factory.local.toml` and enter verified root
paths. The existing local installation already contains the three inspected paths.
Absolute paths, receipts, logs, SQLite and worktrees are ignored by Git.

```sh
./factory prep voice-lab                 # zero model turns; inspect repo hygiene/profile
./factory compile voice-lab --max-tasks 50  # zero model turns; preview deterministic batches
./factory plan voice-lab
# Explicitly authorizes local product work within configured policy:
./factory run voice-lab --max-tasks 8
```

A plan checks realpath, remote identity, HEAD, current remote default SHA, dirty
state, unfinished Git operations, current instructions and related issues/PRs.
`plan` does not fetch into or modify the product checkout. `run` may fetch a
missing base and create its own worktree, preserving unrelated changes.

Current adapters preserve these boundaries:

- **Vedokrok:** website/public delivery; MHC authoring records are not release truth.
- **Ptichi Site:** website; no invented recorder, microphone or installer availability.
- **Voice Lab:** runtime; tests are not device, user, listener or release proof.

Factory deterministically reads `factory-task` JSON blocks from the **existing**
backlog/current-loop file or GitHub issue. See [task contract](docs/TASK_CONTRACT.md).
It never creates another backlog, enables Issues, or manufactures work. Missing
contracts, capabilities, conflicting authority or higher-risk approval return
`NATIVE_HANDOFF` with current repository/authority references. Issues are disabled
in Vedokrok and stay disabled. SDK connector inventory is not assumed to be a
programmatic GitHub API: `allow_gh=true` explicitly permits the authenticated CLI
fallback for the controller. No functioning route means a precise blocker.

## Policies and accounting

Defaults are in `src/devfactory/defaults.toml`; ignored local config can override
profile models/efforts, named checks, reserves and execution limits. Every model
candidate is validated against the live catalog. Unsupported effort falls back to
the catalog default; an unavailable ladder falls back to verified native/default.
Unknown quota pauses. Shared quota exhaustion never triggers model switching.

The default quality/cost ladder is: low-risk strongly verified work → GPT-6 Luna/low;
ordinary work and clean independent review → GPT-6 Sol/medium; high-complexity work,
high-risk review, or review after a repair/escalation → GPT-6 Astra/high. These are
routing defaults, not a claim of measured savings, and unavailable models fall through
the live-verified ladder.

One worker, up to six turns **per task**, up to 60 turns per foreground queue,
a 30-minute queue deadline, 500,000 observable-token **soft queue envelope**, two
repair rounds, one escalation and 10% allowance reserve are starting defaults.
A queue continues only across disjoint declared file scopes; overlap stops before
another model turn because separately reviewed worktrees are not an implicit merge.
A later `run` skips matching terminal receipts at zero model cost and continues to the
next backlog item; `--max-tasks` therefore limits new work, not already completed work. With
`finish_started_task=true`, the soft token envelope stops additional queue work but
does not strand an already-started task before its bounded review/repair gate. Deadline,
turn count and quota remain hard dispatch gates. Repair turns continue directly in the
already-attached builder thread and send only new delta evidence (findings, validation,
changed files) rather than replaying the immutable contract; `thread/resume` is reserved
for actual controller/runtime recovery. Model-facing task
packets contain only the implementation contract fields needed by the worker; controller
routing metadata and unrelated backlog authority stay out of model context. Review is
evidence-first: passing controller checks are not repeated unless the reviewer has a
specific unresolved concern. Focused checks run before broad final checks.

Current context utilization, serving model without telemetry, and parent-chat usage
are reported as unknown. Receipts include per-turn/check durations, active execution
seconds excluding pauses, packet/instruction byte counts, estimated repeated packet
bytes avoided, cached-input ratio when observable, and soft-budget overshoot. Byte
counts are not tokens and cached input is not zero-cost. Missing intervening usage
keeps per-role attribution unknown.

Factory may compact a continuing builder thread before a repair after two completed
builder turns. It first saves a mode-0600 checkpoint with the task contract, base and
source fingerprints, changed paths, check outcomes, findings and remaining budgets.
It skips explicit compaction when token usage is unknown or configured token/turn
reserves for repair and fresh review are not available. Native SDK autocompaction stays
enabled. Each repair re-receives the bounded task contract after compaction, and an
ambiguous result stops for reconciliation. Compaction usage is not separately exposed,
so this is a context-continuity safeguard, not a demonstrated token saving.

Remote integration is disabled; no automatic merge/deploy exists. Optional draft
PR integration needs explicit owner policy plus current trigger/spend/restriction
approval, exact reviewed state and passed local checks. A dedicated private fixture
passed real push/PR and ambiguous-write recovery; product remote integration is
still unverified. The parent skill attaches any created PR.

## Benchmarks and evidence

```sh
./factory benchmark          # offline, zero model turns
./factory benchmark --live   # synthetic model/effort routing comparison inside Factory
.venv/bin/python scripts/evaluation/run.py --experiment policy-v2-r1  # prepare, zero model turns
.venv/bin/python scripts/evaluation/run.py --experiment policy-v2-r1 --live --case small --variant native
.venv/bin/python scripts/evaluation/run.py --experiment policy-v2-r1 --live --case small --variant factory
.venv/bin/python scripts/evaluation/export.py --experiment policy-v2-r1
```

The live fixture command runs Factory in both arms and compares model/effort routing.
The separate evaluation harness uses direct SDK execution for the native baseline,
with identical pairwise source/spec/checks and isolated histories. Each new policy or
replicate uses an explicit experiment namespace, so historical receipts cannot be
mistaken for current-policy evidence. Five pairs have
run; completed-work cost savings are unproven. Read the [results and limitations](docs/benchmarks/RESULTS.md)
and [reproduction protocol](docs/benchmarks/METHODOLOGY.md).
See [capability matrix](docs/CAPABILITIES.md), [architecture](docs/ARCHITECTURE.md),
[limitations](docs/LIMITATIONS.md), [live receipt](docs/receipts/live-smoke.json),
and [benchmark template](docs/BENCHMARK_TEMPLATE.md).

## Uninstall

```sh
python3 scripts/user_skill.py disable  # only if you enabled this installation's link
python3 scripts/uninstall.py
```

Uninstall removes only the marked local virtual environment. Source (including
repo skill), receipts, product work and worktrees remain recoverable. No global
Codex setup is removed. Do not delete `.factory/worktrees` as routine cleanup.


## Lean batch policy (v3)

A foreground `run` reads GitHub/base/backlog authority once, freezes that planning snapshot, and groups
only contiguous compatible tasks that share a context root, routing profile and risk class. Defaults cap a
micro-batch at 4 tasks, 24 declared paths, 6 focused checks and a 12 KB model packet. Remote PR integration
forces single-task mode so exact integration approvals remain task-bound.

The worker receives a small task-local file registry, not a whole-repository map. Historical benchmark data,
receipts, archives and generated output are cold by default and do not enter that navigation capsule unless
the task explicitly scopes them. Successful test stdout/stderr is discarded; only failed checks receive a
bounded redacted local log plus the smaller repair excerpt. Compatible task checks are deduplicated and broad
final checks run once for the whole batch. Strongly verified low-risk batches use the fast review profile;
repairs, high risk and deep work still promote review strength.

Installed plugins remain deferred in child workers. Unsupported external capabilities are returned as an
explicit native capability route instead of loading every tool definition into every coding turn.


## Repository prep and hygiene (v3.1)

Every product `run` now prepares the exact base SHA before the first model turn. This is deterministic Git
analysis, not an AI scout. It writes an ignored local profile under `.factory/projects/<project>/repo-profile.json`
and never edits product files.

Prep measures tracked file/byte counts, root and directory width, large tracked blobs, tracked archive/build/generated
trees, and `AGENTS.md` size/broad-read rules. Known archive/generated roots become **cold context** automatically:
they remain in Git but disappear from normal agent navigation unless the current task explicitly targets them.
This is the safe default form of cleanup because it speeds agent exploration without deleting history or source.

Prep also derives a bounded **co-change graph** from recent Git history. Two backlog tasks from different path roots
can share a micro-batch only when the history shows a repeated, sufficiently strong co-change relationship. Bulk
commits are excluded from this signal. This makes batching follow the repository's real change topology rather than
folder names alone.

`factory prep <project>` exposes the profile for inspection. `factory run` refreshes it automatically, so prep is
not a required manual phase. Destructive cleanup—deleting tracked files, rewriting history, moving source trees,
pruning branches, or changing product instructions—remains explicit reviewed product work.

`factory compile <project> --max-tasks N` is a zero-model-turn backlog compiler. It reads the current authority once,
uses the same repo profile and batching policy, and writes a local campaign artifact showing the batch DAG-like order,
task membership, paths, checks, risk and model profile. It is optional diagnostics; normal `run` retains the compact
foreground loop.


## Optional post-review composition

Pre-build micro-batching is the normal fast path. A second, optional primitive preserves the useful part of PR #3:
separately reviewed `READY_LOCAL` slices that share an exact base and have disjoint scopes can be composed later
without another implementation turn.

```sh
./factory batch <run-id> <run-id> [...]
./factory batch-review <batch-id>
./factory batch-integrate <batch-id>  # optional, explicit remote draft PR
```

`batch` is deterministic and uses zero model turns. It rechecks each reviewed fingerprint, applies the exact
tracked/untracked deltas into a fresh Factory worktree, commits that exact tree, verifies the resulting file set, and writes an idempotent
composition receipt. `batch-review` then runs the configured broad final checks once and spends exactly one fresh
integration-review turn across all child acceptance criteria. It never auto-repairs a failed composition; a defect
blocks the batch instead of mutating already-reviewed slices.

`batch-integrate` is a separate remote-write command. It requires a `BATCH_READY_LOCAL` receipt,
`integration.push = true`, `integration.pull_request = true`, the project's `allow_gh = true`,
and an exact owner approval at `projects.<project>.batch_integration_approvals.<batch-id>`.
Copy `batch_fingerprint`, `base_sha`, `trigger_hash`, and `authority_hash` from the
`integration_candidate` in the ignored `batches/<batch-id>/integration.json` receipt;
set `triggers_reviewed`, `spend_reviewed`, and `owner_restrictions_reviewed` only after
checking the actual remote/hosting effects. The command rejects a changed base, head, scope,
approval, or review, then pushes the reviewed commit and reconciles exactly one draft PR.
Ambiguous push/PR responses are checked against the remote before a retry. No merge or deploy occurs.

This layer is intentionally optional: do not split work merely to use it. The ordinary v3.1 repo-aware micro-batch
path is cheaper when tasks can be safely implemented together from the start.

### Phase B review-deferral experiment (opt-in, local)

With `batching.enabled = false` in ignored local configuration and remote integration disabled,
`./factory run <project> --max-tasks N --experimental-defer-review` first checks that all N selected
tasks share one base, have disjoint scopes, and are low risk, low complexity, and strongly verified.
It refuses the cohort before a model turn if any condition fails. Each clean slice still runs its
configured checks, but ends as `REVIEW_DEFERRED_LOCAL`: acceptance has **not** passed yet. A repair,
escalation, or uncertain builder verdict triggers the ordinary fresh per-slice review and stops
the deferred cohort.

```sh
./factory batch <deferred-run-id> <deferred-run-id> [...] --deferred
./factory batch-review <batch-id>
./factory resume <deferred-run-id> --review-deferred  # fallback when no full cohort is available
```

The deferred batch rechecks every source fingerprint and validation receipt, commits exact
disjoint deltas, runs the combined final gate, and spends one fresh integration-review turn
covering every acceptance criterion. A failed check or review blocks the batch; no automatic
repair, merge or deploy occurs. `batch-integrate` retains its separate exact owner-approval gate.
The offline fixture shows the turn-count mechanism, not a quality or cost saving. Promotion
requires paired Phase A/direct-native evaluation with task/oracle success, review findings,
model-turn counts, input/cached/output tokens, latency and completion receipts. Unknown telemetry
remains unknown.

Composition, integration review, and explicit remote integration share the ordinary runner's global worker lock and
lease. Their run IDs appear in `status`/`report`; `pause <run-id>` requests a review
pause and `resume <run-id>` reconciles the saved batch operation. A live lease is never
stolen. Review dispatch, native thread/turn identity and observed usage are persisted
before/during the turn. A lost result is recovered from the same native turn when its
completed verdict is available. Missing acknowledgements, active/interrupted turns or
unavailable verdicts block without a second review; inspect the preserved checkpoint.
Recovered usage is explicitly incomplete when final telemetry was not observed.

Planning checks task authority before computing a repository profile. Unavailable or
timed-out co-change history is recorded as unknown; batching then requires shared task
roots and cannot infer cross-root relationships from missing history.
If the optional full-tree hygiene scan is unavailable, its counts and byte totals
stay unknown and navigation includes only declared task/guidance paths. Authority,
scope, source fingerprints, required checks and independent review still run.

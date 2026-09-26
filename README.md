# DevFactory

A local foreground control layer over the official Codex Python SDK. It selects
verified model/effort profiles, runs one bounded task at a time, preserves work,
and leaves inspectable test, review and usage receipts. Models run remotely;
Git, builds, tests and the supervisor run on your Mac.

**Working MVP, not an efficiency claim.** Native models and autocompaction remain
the defaults. Initial setup never starts development in product repositories.

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
./factory plan vedokrok
./factory plan ptichi-site
./factory plan voice-lab
# Explicitly authorizes one local product cycle within configured policy:
./factory run <project> --max-tasks 1
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
mapping is validated against the live catalog. Unsupported effort falls back to
the catalog default; unavailable model falls back to verified native/default.
Unknown quota pauses. Shared quota exhaustion never triggers model switching.

One worker, six turns, 30-minute foreground deadline, 150,000 observable-token
**soft** budget, two repair rounds, one escalation and 10% allowance reserve are
starting defaults. There is no hard in-flight token cap. A turn can overshoot the
soft budget; Factory stops issuing subsequent turns. Current context utilization,
serving model without telemetry, and parent-chat usage are reported as unknown.

Remote integration is disabled; no automatic merge/deploy exists. Optional draft
PR integration needs explicit owner policy plus current trigger/spend/restriction
approval, exact reviewed state and passed local checks. It has simulated write
coverage, not production proof. The parent skill attaches any created PR.

## Benchmarks and evidence

```sh
./factory benchmark          # offline, zero model turns
./factory benchmark --live   # explicit real native-vs-Factory fixture pair
```

The live baseline preserves native model/effort/context defaults. Variants share
the starting commit/spec/tools/tests but not completed solutions or histories.
The full live comparison has **not** run. No savings percentage is supported.
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

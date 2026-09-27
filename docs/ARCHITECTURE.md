# ADR 001: one local supervisor, official Codex runtime

Status: implemented MVP, 2026-09-26.

The small Python process owns task contracts, policy, budgets, leases, checkpoints,
usage observations and receipts. The official `openai-codex` SDK and its matching
CLI-bin own authentication, model/tool loops, native repository instructions,
autocompaction and sandbox. No OpenAI API client or custom AI runtime exists here.

`Runtime` uses public SDK client methods. Start/stream uses the SDK's per-turn
subscription API; raw `turn/start` plus the global notification stream loses events
in SDK 0.157.1. A narrow allowlisted RPC adapter handles inventory, quota, sandbox
commands and compaction state not exposed by the high-level convenience API.
Experimental APIs and remote WebSockets are disabled.

The lifecycle is refresh → select → claim → build → validate → fresh review →
bounded repair → ready/blocked → receipt. No separate Codex Goal controls child
work. Native multi-agent is deliberately disabled inside a task: implementation,
repair and review touch one mutable change set, while parallel subagents can add token
overhead and coordination without independent write domains. Parallelism remains an
evaluation target for future read-only research or truly independent repositories.
One flock/SQLite lease serializes all configured projects for this installation;
there is no claim of exclusivity over other installations, humans or Codex clients.
No TTL-only takeover is allowed. Only explicit resume can recover a dead lease.

The builder has a Factory-owned Git worktree. Review uses a fresh native thread and
an isolated copy of the actual base plus diff and untracked task files. Its workspace
sandbox permits temporary test writes. The controller checks both snapshots for
source changes. Review never receives builder conversation or hidden reasoning.

Factory policy v2 routes by task/role through a live-catalog ladder: Luna/low for
strongly verified low-risk work, Sol/medium for ordinary work and clean review, and
Astra/high for deep work plus high-risk or post-repair review. Unavailable candidates
fall through to the next verified entry and ultimately native/default; quota pressure
never causes a model switch. Repeated implementation failure may escalate the builder
to the deep profile. Native baseline still omits both model and effort overrides.
Both benchmark variants use identical tools, acceptance, tests and starting commit,
with separate worktrees/threads and no solution or receipt sharing.

Builder repair turns stay in the same native thread and receive only delta evidence.
Within one live Runtime process they continue directly on that attached thread; the
resume RPC is used only when a controller/runtime restart must reattach durable state.
Fresh reviewers receive the bounded implementation contract, summarized check outcomes,
task-relevant guidance paths and diff access. Controller-only routing metadata and
unrelated backlog authority are not copied into model context. Review is evidence-first:
a passing controller check is rerun only for a concrete unresolved concern. Turn limits
are two-level: each task is independently bounded by `max_turns`, while
`max_queue_turns` caps aggregate autonomous work across the foreground queue; the
token envelope and deadline remain queue-wide. Queued tasks must also have disjoint
declared scopes. An overlap stops before another model turn because independently
reviewed worktrees from the same base are not a safe implicit merge. This preserves a stable prompt prefix
and avoids replaying logs, policy metadata and the whole contract on every repair.
Deterministic validation is staged: focused task checks first, broad final checks only
after the focused stage passes.

Current repository/GitHub data is task authority. An optional `factory-task` JSON
contract in an existing issue/backlog makes acceptance and file scope deterministic;
it is not a second backlog. Arbitrary prose is handed to native Codex for selection.
No classifier model is required in this MVP. Named validation commands come exclusively
from owner configuration, never issues or model output. Untrusted task input uses the
SDK's supported tool-output authority (`ExternalMessage` wire representation).

Remote integration is off. The opt-in adapter supports draft PR creation with
read-before-retry reconciliation; it has only offline/simulated GitHub write tests.
MVP code refuses automatic merge/deploy. The parent skill attaches any resulting PR
with the native Codex tool. CI unknown/not-started never becomes PASS.

Stored metadata includes repository/task IDs, SHAs, named command results, usage,
selection reasons, review outcomes and operational checkpoints. Native Codex retains
its own sessions through normal authentication; Factory does not copy conversations,
reasoning, credentials or auth files. Local logs hold redacted validation output,
not raw model/tool transcripts. Redaction is defense in depth, not a universal PII detector.

Foreground operation is deliberate. Sleep or process death does not promise progress.
SIGINT/pause requests interruption, writes a checkpoint and preserves work. Resume
reconciles current task authority, config, native turn, base, branch, file fingerprint
and (before integration) remote branch/PR state.


## Policy v3: context-local micro-batches

Policy v3 changes the unit of work from an issue-sized turn sequence to a compatible micro-batch. The
controller freezes one GitHub/base/authority snapshot per foreground queue, then greedily groups only
contiguous tasks with the same profile/risk and a shared two-level path context. Batch size, paths, checks
and serialized task packet all have hard caps. One worktree and builder thread implement the batch, task
focused checks are deduplicated, broad final checks execute once, and one fresh reviewer judges every member
acceptance criterion. Individual task keys are persisted as aliases to the batch receipt, so later runs remain
idempotent even when invoked with a smaller `--max-tasks`.

Repository navigation is deterministic and controller-owned: it indexes the exact base tree but exposes only
guidance, scoped files, siblings and root build/config hints. Cold prefixes are counted but omitted unless the
task explicitly targets them. This avoids the stale "read a full repo map first" pattern while still reducing
repeated tree exploration.

Passing validation no longer writes stdout/stderr logs. Failed validation keeps only a bounded redacted tail;
the model receives the still-smaller failure excerpt. A clean low-risk fast batch uses `review_fast`; any
repair, escalation, deep profile or high risk retains stronger review. Plugins/MCP stay disabled inside child
workers; external capability routes are deferred to the native parent surface rather than eagerly expanding
every worker's tool context.


## Policy v3.1: repo compiler before model execution

Before the first model turn, the controller derives an exact-base repository profile from Git metadata. The profile
contains structural metrics, cold-context prefixes, instruction-hygiene findings and a bounded co-change graph from
recent commits. It is persisted under Factory state, keyed by base SHA, and refreshed automatically when the base
changes. No repository file is modified by prep.

The co-change graph works at bounded component-root granularity. Large/bulk commits are ignored; edges require both a
minimum repeat count and confidence. Batch selection first accepts identical context roots, then may accept a different
root only through this graph. This is evidence for likely shared implementation context, not proof of dependency.

Repository cleanup is intentionally asymmetric: safe visibility cleanup is automatic; destructive cleanup is not.
Tracked archive/generated/build-style roots can be hidden from ordinary model navigation, while deleting, moving or
untracking those files must be normal reviewed work. Instruction bloat, wide directories and large tracked blobs are
reported as findings rather than silently rewritten.

The optional campaign compiler reuses the same frozen GitHub/authority snapshot and repo profile to emit a local,
zero-model-turn sequence of bounded batches. It is an observability/planning artifact, not a second backlog and not an
extra mandatory phase.

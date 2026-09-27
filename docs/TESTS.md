# Verification performed

Batch safety regression coverage includes the global worker lock and live lease,
contention during validation/review, saved-result and native-turn recovery, unknown
dispatch acknowledgement, active/interrupted turns, pause/deadline gates and explicit
dead-owner resume. These cases use offline synthetic repositories and FakeRuntime;
they do not establish live product execution or complete missing usage telemetry.

Current offline suite: **133 passed** on Python 3.11.16 / macOS arm64 (2026-09-27). GitHub Actions also runs the suite on Ubuntu with the pinned SDK/runtime dependencies.
Planning regressions distinguish a clean ancestor checkout from edited, deleted or
independently committed local governing instructions, without changing that checkout.

- Policy: available/unavailable models and effort, verified fallback, modality,
  unknown/exhausted/relevant quota, reserves, deadline, repairs/escalations.
- Accounting: duplicate/cumulative snapshots, nested token categories, missing
  values, repair deltas, no invented context utilization or effective model.
- Context: request vs completion, duplicate item, no-op, failure, timeout,
  active-turn rejection and independent review without builder history.
- Leases: competing workers, live expired lease, explicit dead-worker recovery.
- Files/recovery: foreign dirty work preserved, isolated review scratch, pause/resume,
  changed checkpoint, changed authority, repeated completion and two-task queue.
- Integration: missing GitHub, plugin handoff, disabled Issues/file authority,
  unmerged dependency, missing validation executable, stale review SHA/unknown checks,
  ambiguous PR creation and crash-before-receipt recovery using simulated GitHub.
- Policy/security: injected command/config fields rejected, secret-read/sandbox/policy
  requests handed off, high-risk labels cannot downgrade guarded paths, explicit
  no-permission approval responses and non-allowlisted RPC rejection.
- Compatibility/packaging: pinned installed SDK methods/schemas, unsupported version
  rejection, CLI grammar, skill/plugin structure and source parity, safe uninstall,
  launcher does not select a product checkout as its installation root.

The offline fake executes real unittest commands against tiny fixture Git repositories.
Its model behavior, usage and GitHub mutations are explicitly synthetic. These tests
are not proof of adversarial sandbox isolation, production CI, or remote PR writes.

The official plugin and skill validators passed. Local installation/reinstallation,
packaged CLI schema, actual-app skill dispatcher `doctor`, runtime skill discovery,
and offline benchmark were exercised. No global plugin/skill was installed.

Real Codex checks are enumerated in [live-smoke.json](receipts/live-smoke.json):
three-request capability spike; bounded edit/test/review cycle with one review-environment
repair; repeated command with no new model turn; completion-race and active-command
interrupt probes. Eight child requests total. Real product runs were not performed. The later explicit evaluation added five
direct-native/Factory pairs, all passing common behavioral checks; Factory default
full workflows completed 2/5. See [evaluation](benchmarks/RESULTS.md).

Reproduce:

```sh
.venv/bin/python -m pytest
./factory doctor
./factory benchmark
./factory doctor --live  # explicit allowance use; idempotent smoke fixture
```

## Evaluation regressions

Added tests reproduce expired-deadline compaction dispatch and missing-usage role
misattribution, then verify the fixes. Actual adapter-path tests cover persisted
completion/no-op/failure/interruption/timeout. Unused context-policy/FSM tests were
removed, so the count is not directly comparable to the old 86.

Review rejection/repair, real-process dead lease, failure after local commit before
validation, active-time exclusion of paused downtime, and explicit rejection of the
inert automatic-compaction flag are covered. A dedicated private fixture also passed
real push/PR recovery after two injected controller failures, with no repeated model
turns or PR. Runtime pins remain 0.157.1.

The separate long recovery probe confirmed active interruption, compaction completion,
unchanged files through compaction and same-thread continuation. Its final code
passed 916 tests and the independent oracle. The 500k experimental soft budget was
exceeded before review (838548 cumulative observed tokens), so the workflow remains
PAUSED_BUDGET; recovery through fresh review is only partially verified. Two tests
also prevent completed evaluation scripts from redispatching work or overwriting
the original receipts when invoked again.

The live routing benchmark preserves its existing project/run identities while
comparing native versus policy-v2 model/effort routing inside the same Runner;
repeating it under a fake runtime reuses both receipts and adds zero model turns.

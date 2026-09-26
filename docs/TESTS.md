# Verification performed

Final offline suite: **86 passed** on Python 3.11.16 / macOS arm64.

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
interrupt probes. Eight child requests total. Real product runs and full live
native-vs-Factory benchmarking were not performed.

Reproduce:

```sh
.venv/bin/python -m pytest
./factory doctor
./factory benchmark
./factory doctor --live  # explicit allowance use; idempotent smoke fixture
```

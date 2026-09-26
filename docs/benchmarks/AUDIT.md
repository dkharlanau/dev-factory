# Implementation audit at 6087606

Baseline: clean `codex/dev-factory`, initial offline suite 86 passed; doctor reports
ChatGPT authentication, SDK/runtime 0.157.1, native gpt-6-astra/xhigh and seven catalog
entries. Doctor consumes zero model turns. No version mismatch was observed.

| Area | Evidence and discrepancy |
|---|---|
| Selection | Catalog validates model and effort; missing model/native fallback and higher-risk routing have tests. No real cross-model efficiency evidence. |
| Contracts | Current file/issue authority, owner-named commands, dependencies and path scopes are enforced. Unstructured task selection is unsupported and hands off. |
| Budgets | Soft tokens gate the next external turn; a single native turn can exceed the entire threshold. Current usage is not active context. Primary evaluation preserves these semantics. |
| Compaction | Native autocompaction is enabled. Manual adapter exists and has previous live proof; `context_decision` and `context.manual_compaction` are **not wired into Runner**. There is no automatic Factory early-compaction policy. Earlier wording about optional policy was too broad. |
| Leases | Flock plus SQLite process identity prevents simultaneous Factory workers within one state root. TTL does not authorize stealing. Different installations and native/manual workers are outside this lock. |
| Isolation | Builder worktree and separate writable review snapshot preserve foreign work. Git isolation is not a secret-read sandbox. |
| Pause/resume | Checkpoints reconcile authority/config/base/branch/fingerprint/native in-flight state; budgets remain cumulative. Existing wall_seconds includes paused downtime, so it is not active processing time. |
| Interrupt | Public turn interrupt awaits authoritative terminal state or reports unconfirmed. Transport-level failure is distinct from an implementation defect. |
| Duplicate execution | Completed-task key/contract/base prevents fresh execution; in-flight ambiguity hands off. Existing remote PR is looked up before create. Actual remote failure recovery is tested separately. |
| Review | Separate thread/snapshot, actual diff and current tests; no builder transcript. Source fingerprints and committed HEAD/base bind integration. A blocked or skipped review is not READY_LOCAL. |
| Receipts | Cumulative token accounting correctly avoids adding cached/reasoning subsets. Missing effective model/occupancy remains unknown. Missing per-turn latency and validation duration limit attribution; workflow wall_seconds alone mixes active time and pause. |
| Old benchmark | `benchmark --live` uses Runner for both arms with baseline=True changing only selection. It is a profile comparison inside Factory, **not direct native vs Factory workflow evidence**. New evaluation uses direct Runtime/SDK for native. |
| Commit order | With integration enabled, the controller commits before validation/review so the exact committed SHA is reviewed. Failures preserve that local commit and never automatically push it. This differs from a literal review-then-commit diagram but preserves the important remote gate. |

All assertions are version-bound. Public protocol reference:
[Codex App Server](https://learn.chatgpt.com/docs/app-server). The installed stable SDK
and observed events, not current documentation alone, establish local capability.

Additional offline tests exercise review rejection → repair → different fresh
reviewer, failure after commit before validation with no repeated builder/commit,
and an actual subprocess dying while holding its lease followed by explicit recovery.
These tests use synthetic model output; they are not live-model reliability rates.

A second compaction test gap was found while following actual call sites: the
`Compaction` event FSM was unused by `Runtime.compact`, which observes persisted
thread state. Its simulated completion/no-op/failure tests therefore did not test
the production adapter. The adapter also dispatched `thread/compact/start` when
called with an already expired deadline. Correcting that admission defect and
replacing dead policy tests with adapter-path tests is justified; it does not
replace native context management.

The global notification listener also retained a second queue with no consumers.
A zero-model inventory probe observed two retained notifications (about 1307 Python
object bytes, an upper estimate with shared references counted repeatedly). This
is not material token/performance savings. The redundant queue is removed while
keeping the SDK global stream drained and real turn subscriptions intact.

Role attribution had a reproducible missing-telemetry defect: after a turn without
usage (for example compaction), the next cumulative snapshot was treated as if that
thread started at zero. A 100-token build, unknown compaction, then cumulative 160
could incorrectly attribute all 160 to repair. Overall per-thread budget totals were
not affected. A regression test requires unknown role allocation across that gap.

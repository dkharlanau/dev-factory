# Supported subset and limitations

- Native/default model IDs are preserved. Profiles select supported effort; no measured
  speed, quality or subscription-efficiency advantage has been established.
- Real worker/edit/test/fresh-review/resume/manual-compaction tests passed on the pinned
  Mac environment. Only Astra low/medium turns were exercised, not every catalog model.
- Initial smoke used exactly three requests, including compaction. Its controller event
  bug lost builder/compaction token telemetry. The error and recovery are preserved.
- Compaction completion is confirmed by documented persisted turn/item state. SDK
  0.157.1 does not expose a pre-registered subscription for its unknown compaction turn
  ID. Live success was observed; no-op/failure/duplicate handling is tested offline.
  Its usage remains unknown. Native autocompaction stays enabled; optional policy cannot
  trigger early compaction without verified active-window/headroom semantics.
- A runtime-reported model context window is available; current context occupancy is
  unknown. Cumulative tokens are not context occupation. Requested/resolved model is
  not proven serving model; effective model stays null without reroute telemetry.
- Quota is account-wide. Unknown relevant allowance pauses. No paid fallback, credits
  purchase or reset-credit action exists. Token soft budgets gate the next turn; one
  turn can cross the threshold. The tested cycle used 194,779 observed tokens against
  a 150,000 soft threshold because its last review began below that threshold.
- The parent Desktop conversation and setup overhead are unmeasured. Final completion
  cost includes failed attempts and repeated review, not just the successful builder.
- Product adapters read current repo identity/default SHA/instructions/PRs/issues.
  Unstructured priorities return NATIVE_HANDOFF with current authority references.
  Existing backlogs need explicit scope/acceptance contracts and owner check allowlists
  for deterministic execution. No tasks were started in the three product repositories.
- Voice Lab's current main-only instruction conflicts with Factory worktree branches.
  Ptichi Site's verified remote base was absent from its configured local checkout at
  setup; plan reports this, run can fetch before isolation. Vedokrok Issues are disabled;
  file authority remains authoritative. None of these states means zero available work.
- SDK skills/plugins/MCP inventory is not proof every connector works. Desktop-native
  codex_app tools were absent in child inventory. The local worker intentionally scopes
  out unneeded apps/MCP/plugins and network, using supported per-process/thread overrides.
  Plugin-dependent work currently hands off; no plugin behavior is emulated.
- Authenticated gh read operations passed. Remote push/PR recovery is simulated offline;
  no real PR, merge, deploy, repository settings change or scheduled run occurred.
- Native sandbox is retained. Workspace isolation is not a security sandbox. The pinned
  public workspace-write schema does not provide per-file secret-read denial. Policy
  screening, tool-level input authority, scoped tools and post-edit path checks do not
  claim perfect prompt-injection prevention. Sensitive/ambiguous tasks hand off.
- Review gets an isolated writable snapshot; large projects may need dependencies in
  that environment. Missing tooling or permissions pauses/hands off, never silently
  reruns a build outside the runtime sandbox.
- One foreground worker per installation. Persistence after closing Codex, sleep or
  termination is not promised. A live lease is not stolen even after a long sleep.
- Full live native-vs-Factory benchmarking has not run. It requires `benchmark --live`.
  An offline benchmark tests policy correctness and reports zero model performance samples.

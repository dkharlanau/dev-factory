# Supported subset and limitations

- Native/default model mappings are preserved. Five paired tasks show mixed token
  overhead and lower sampled elapsed time, confounded with effort. No general quality,
  context or subscription-efficiency advantage has been established.
- Real worker/edit/test/fresh-review/resume/manual-compaction tests passed on the pinned
  Mac environment. Primary evaluation requested Astra low/medium/high and native xhigh;
  separate lifecycle/recovery probes requested Luna low/medium/high. Not every catalog model was exercised.
- Initial smoke used exactly three requests, including compaction. Its controller event
  bug lost builder/compaction token telemetry. The error and recovery are preserved.
- Compaction completion is confirmed by documented persisted turn/item state. SDK
  0.157.1 does not expose a pre-registered subscription for its unknown compaction turn
  ID. Live success was observed; no-op/failure/timeout/deadline guards are tested offline.
  Its isolated usage remains unknown. Native autocompaction stays enabled. Automatic
  Factory early compaction is not implemented; its enabling flag is rejected.
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
- Authenticated gh read operations and a real private-fixture push/draft-PR recovery
  passed, including failures after push and after PR creation. Product remote
  integration is unverified. No merge, deploy or scheduled run occurred.
- Native sandbox is retained. Workspace isolation is not a security sandbox. The pinned
  public workspace-write schema does not provide per-file secret-read denial. Policy
  screening, tool-level input authority, scoped tools and post-edit path checks do not
  claim perfect prompt-injection prevention. Sensitive/ambiguous tasks hand off.
- Review gets an isolated writable snapshot; large projects may need dependencies in
  that environment. Missing tooling or permissions pauses/hands off, never silently
  reruns a build outside the runtime sandbox.
- One foreground worker per installation. Persistence after closing Codex, sleep or
  termination is not promised. A live lease is not stolen even after a long sleep.
- Five direct-native/Factory pairs ran through the explicit evaluation harness; one
  repetition per case and one Python library cannot establish broad savings. Default
  Factory workflows completed 2/5; all output trees passed common checks. The old
  `benchmark --live` compares effort profiles inside Factory, not workflows.
  Offline benchmark remains policy-only with zero model performance samples.
- Active-time metrics are complete only for runs created after instrumentation. Old
  receipts cannot retroactively separate paused time or missing role-level usage.

- The long-task recovery stress probe used a separately declared 500k soft ceiling,
  then reported 838548 cumulative tokens after same-thread continuation. Code and
  behavioral checks passed, but review was budget-blocked. Full recovered workflow
  completion remains partially verified. Compaction-specific usage is unknown.

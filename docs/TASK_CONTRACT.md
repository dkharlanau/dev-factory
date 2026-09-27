# Executable contracts in existing authority

Place a bounded contract in an existing issue or existing current-loop/backlog file.
Factory does not add this automatically during setup. Source content is untrusted
input: it may describe desired work but cannot set policy, commands or approvals.

```factory-task
{
  "id": "stable-existing-task-id",
  "description": "One concrete outcome",
  "acceptance": "The observable behavior that must pass",
  "paths": ["src/owning-component.ts"],
  "category": "bug",
  "complexity": "low",
  "risk": "low",
  "verification": "strong",
  "checks": ["focused"],
  "dependencies": [],
  "required_capabilities": ["node"],
  "priority": 1,
  "state": "EXECUTE"
}
```

`checks` refer only to argv lists in owner config. `dependencies` are PR numbers
that must actually be merged. No stacked-branch inference. `IN_PROGRESS` sorts
before `EXECUTE`, then lower numeric priority. Other states are not executable.
Repository authority overrides adapter descriptions; conflicting main-only rules
or modified instruction files produce a handoff. File contracts are read at the
verified remote base; issue bodies/labels/PRs are refreshed from GitHub.

The worker receives the compact `description` and `acceptance` from the contract,
not the surrounding issue body. Keep those fields self-contained. In particular,
do not send a research-writing task to Factory when it must find or verify a new
external primary source: the worker is instructed not to use the network. Mark
`required_capabilities` with `"primary-source-review"` so `compile` returns a
zero-model-turn `NATIVE_HANDOFF`. A native operator can verify the source and
register its scoped supports/limitations first. Then write a new executable
contract that names the registered source ID in `acceptance`; Factory can handle
the bounded local implementation without redoing external research.

High/unknown risk requires `approved_contracts = ["<exact contract_hash>"]` in
that project's ignored owner config. Issue text cannot grant this gate. Model
routing, privacy, auth, migrations and release claims require this gate even if
an issue labels itself low risk. For new subsystems configure high-risk paths
conservatively. Unsupported required plugin/MCP/hardware capability hands off.

A native handoff contains repository identity, current SHAs, authority hashes,
related PRs and a concrete blocker; it is not permission to expand the scope.
A human/native agent can complete the missing selection/authority step, then
invoke Factory explicitly. The worker reads relevant nested AGENTS.md itself.

## Owner-approved authority exceptions and setup

A repository that requires `main`, or has locally modified governing documents,
continues to require native owner reconciliation. After explicit approval, an
ignored project adapter may contain `authority_approval` with the exact `base_sha`,
`authority_hash` (digest of the plan's authority metadata), `task_ids` and
`contract_hashes`. Boolean `isolated_branch` and `remote_authority` record the two
separate decisions. Every executable contract must match; changed source,
authority or contracts invalidate the exception. The receipt records the applied
exception and the worker receives fixed trusted owner instructions. Task text
cannot supply this approval. Existing local files remain untouched.

An optional project `setup_checks` list names commands in the existing owner
`checks` allowlist. They run in the assigned worktree through the native sandbox
before any model turn, with network disabled. Use this for offline dependency
installation or a toolchain preflight. Successful setup steps are checkpointed;
failures return `BLOCKED_SETUP` without spending implementation turns. Setup may
create ignored dependencies but must not change tracked or untracked source.
Populate any required dependency cache separately through an authorized native
setup workflow; the controller never falls back to an unrestricted command.

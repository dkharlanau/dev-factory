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

High/unknown risk requires `approved_contracts = ["<exact contract_hash>"]` in
that project's ignored owner config. Issue text cannot grant this gate. Model
routing, privacy, auth, migrations and release claims require this gate even if
an issue labels itself low risk. For new subsystems configure high-risk paths
conservatively. Unsupported required plugin/MCP/hardware capability hands off.

A native handoff contains repository identity, current SHAs, authority hashes,
related PRs and a concrete blocker; it is not permission to expand the scope.
A human/native agent can complete the missing selection/authority step, then
invoke Factory explicitly. The worker reads relevant nested AGENTS.md itself.

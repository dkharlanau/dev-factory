# Capability evidence — 2026-09-26

This matrix distinguishes documentation from local proof. Versions are not interchangeable.
Initial setup smoke was limited to **three model-producing requests including compaction**.
The later explicit evaluation is described in [benchmarks](benchmarks/RESULTS.md); ordinary tests remain offline.

| Capability | Documented | Locally tested | Unsupported or unknown | Tested version | Evidence | Fallback |
|---|---|---|---|---|---|---|
| macOS / CPU | N/A | macOS 27.2, build 26B5091g, arm64 | Other hosts | OS 27.2 | `sw_vers`, `uname -m` | Doctor refuses unsupported runtime pins |
| Python | SDK requires >=3.10 | system 3.9.6; isolated 3.11.16 | System Python cannot run SDK | 3.11.16 | `.venv/bin/python --version` | Install isolated Python >=3.11 for Factory |
| Desktop app | Separate distribution | app 26.924.22138 (11645) | App is not SDK runtime | 26.924.22138 | Info.plist version fields | No Desktop internals used |
| Installed CLI | Official CLI | 0.158.0-alpha.2.1 | Compatibility not assumed | 0.158.0-alpha.2.1 | `codex --version` | Use SDK bundled runtime |
| Python SDK / runtime | [SDK](https://learn.chatgpt.com/docs/codex-sdk) stable Python release | SDK and CLI-bin 0.157.1; handshake also 0.157.1 | Other versions require retest | 0.157.1 | `.factory/evidence/capabilities.json` | Fail closed on version drift |
| Authentication | [Auth](https://learn.chatgpt.com/docs/auth) | `account/read` type chatgpt, `codex login status` | Separate billing not authorized | 0.157.1 | Doctor auth-mode field | Require official login; never inspect auth.json |
| Model catalog | `model/list` | 7 models; native config gpt-6-astra / xhigh | Catalog is eligibility, not proof every model ran | 0.157.1 | Capability JSON | Policy v2 uses live-catalog ladders with native/default fallback; actual savings require evaluation |
| Effort / modality | Model catalog metadata | Astra/Sol/5.6-Sol/Terra: low..ultra; Luna/5.6-Luna: low..max; 5.5: low..xhigh; text/image | Audio modality not declared | 0.157.1 | Live catalog | Unsupported effort uses declared default; missing text => handoff |
| Subscription telemetry | `account/rateLimits/read` | Independent codex and base_model_inference buckets, percentages/reset times | Account deltas cannot be attributed to this run | 0.157.1 | Redacted inventory JSON | Unknown relevant quota pauses; never consume reset credits |
| Thread/start, turn, resume, fresh review | SDK and [app-server](https://learn.chatgpt.com/docs/app-server) | Start/edit/result/resume + distinct reviewer thread passed | A fork is not fresh context | 0.157.1 | First live smoke receipt | Preserve work; native handoff |
| Sandbox command execution | `command/exec` | Python command exit 0 through workspaceWrite sandbox | Product builds may need additional permissions | 0.157.1 | Probe output | Handoff; no unrestricted shell workaround |
| Manual compaction | `thread/compact/start`, contextCompaction items and turn lifecycle | COMPLETED with contextCompaction item in a persisted completed turn | Request acknowledgement alone proves nothing | 0.157.1 | First live smoke receipt | Disabled by default; native autocompaction |
| Interrupt | `turn/interrupt`; completed status interrupted | Active command interrupted; completed status interrupted observed | Immediate cancellation can race completion | 0.157.1 | Installed SDK public API/schema | Preserve checkpoint; mark unconfirmed interrupt honestly |
| Usage | tokenUsage total/last, nested cached/reasoning, modelContextWindow | input, cached input, output, reasoning, cache writes, total and modelContextWindow observed | Active-window occupation semantics unverified | 0.157.1 | Installed schema and smoke receipt | Unknown stays null; never sum nested token categories |
| Skills in SDK worker environment | `skills/list` | Factory discovered after physical repo skill installation; dispatcher doctor passed | Discovery is not successful task execution | 0.157.1 | Inventory JSON | Explicit local skill path or handoff |
| MCP / apps in child runtime | `mcpServerStatus/list` | GitHub connector tool names and multiple MCP servers visible | Invocation/permissions not established by inventory; Desktop codex_app has no tools | 0.157.1 | Inventory JSON | Required unavailable capability => NATIVE_HANDOFF |
| Plugins | `plugin/list` | RPC responds on stable API | Packaging/discovery != tool functionality | 0.157.1 | Inventory JSON | Never install plugins automatically |
| GitHub CLI | Authorized `gh` | gh 2.97.0 authenticated; all three repositories read | Real private fixture push/PR recovery; product writes unverified | 2.97.0 | Read-only setup | Explicit local policy permits gh only; missing access blocks |
| Native context/subagents/profiles/review | [Native multi-agent](https://developers.openai.com/codex/multi-agent), config docs | SDK stable feature list/schema inspected | Efficiency advantage unmeasured | 0.157.1 | Native features metadata | Reuse native context/sandbox; one sequential Factory worker |
| Worktrees | Native Git / Desktop facilities | Git available | Global exclusivity across humans/agents impossible | Local Git | Fixture integration tests | Factory-owned task worktree, local lock only |
| Durable background execution | Not assumed | Foreground only | Closed app, sleep, killed process continuation unverified | MVP | Pause/resume tests | Explicit foreground resume |

## Public interface boundary

The implementation uses official `openai_codex.client.CodexClient` public methods and
allowlisted documented JSON-RPC methods. It does not access underscored SDK fields.
SDK owns transport, authentication, model/tool execution and sandbox. The high-level
SDK does not expose quota, sandbox command execution, or a compaction completion stream;
the narrow protocol adapter covers these and the same stable lifecycle. Experimental API
opt-in is **false**, unlike the SDK default. No WebSocket remote transport is used.
The app-server page labels remote WebSocket transport/command experimental and unsupported
for production; this MVP uses the published stable Python SDK's pinned local stdio runtime.

## Setup project facts

- `dkharlanau/vedokrok` Issues are disabled. Existing file authority must be used; no new backlog is created.
- A directory named `Developments/vedokrok` actually points at `dkharlanau/mhc-corpus`: rejected as a website checkout.
- The verified website checkout has unrelated dirty work: preserve it.
- Voice Lab currently says work on `main`; Factory's isolated branch policy must surface this conflict before mutation.
- No product work, push, PR, deployment or scheduled run is authorized by setup alone.

## Final verification

The first smoke used exactly three model-producing requests, including compaction.
The end-to-end runner used three more (builder, blocked read-only review, repaired
review environment), then a repeated run consumed none. Two tiny interrupt probes
covered completion-race and active-command cancellation. Total setup child requests: 8.
No full live benchmark ran during initial setup. See `docs/receipts/live-smoke.json` for portable evidence;
full metadata/test logs remain in ignored `.factory/evidence` and `.factory/runs`.

Manual compaction success was verified from persisted `thread/read` turn and
contextCompaction item state. Its completion event stream and its complete token
usage were not observed. No-op/error/timeout/expired-deadline boundaries now have
tests against the actual persisted-state adapter; the unused event FSM was removed.
No arbitrary active-context percentage is derived.

## Subsequent engineering evaluation

Five direct-native/Factory task pairs at `6087606` passed common acceptance. Factory
finished 2/5 reviewed workflows; three paused before review on its default soft budget.
No natural compaction occurred. Effective model and attributable subscription cost
remain unknown. See [results](benchmarks/RESULTS.md) and [portable receipts](benchmarks/results.json).

A dedicated private GitHub fixture verified real push, draft PR, exact reviewed SHA,
recovery after ambiguous push/PR completion, and duplicate suppression with no extra
model turns. CI was absent, not passed. No product release was attempted.

Automatic Factory early-compaction policy was never wired into Runner; it is now
explicitly unsupported and its inert enabling flag is rejected. Native
autocompaction and the explicit manual adapter remain. Initial setup evidence above
is historical; later native-default model drift is recorded per experiment.

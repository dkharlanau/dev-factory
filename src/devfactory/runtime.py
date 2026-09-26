"""Official SDK transport + a small allowlisted stable app-server adapter.

No private fields, custom model calls, tool execution, auth extraction or session DBs.
The high-level SDK omits quota, command/exec and compaction completion subscriptions;
its public CodexClient.request/next_notification provide the documented protocol.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import queue
import threading
import time
from pathlib import Path

from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from pydantic import RootModel

from .policy import Stop

SDK_VERSION = "0.157.1"
RUNTIME_VERSION = "0.157.1"
ALLOWED_METHODS = {
    "account/read", "account/rateLimits/read", "model/list", "config/read",
    "skills/list", "mcpServerStatus/list", "plugin/list", "thread/start", "thread/resume",
    "thread/read", "turn/start", "turn/interrupt", "thread/compact/start",
    "command/exec", "command/exec/terminate",
}
BASE_OVERRIDES = (
    'forced_login_method="chatgpt"', 'model_provider="openai"', 'features.hooks=false', 'features.multi_agent=false',
    'features.memories=false', 'shell_environment_policy.inherit="core"',
    'shell_environment_policy.ignore_default_excludes=false',
)


def dump(value):
    return value.model_dump(mode="json", by_alias=True, exclude_unset=True)


def versions():
    return {"sdk": importlib.metadata.version("openai-codex"),
            "runtime_package": importlib.metadata.version("openai-codex-cli-bin")}


def verify_versions():
    v = versions()
    if v != {"sdk": SDK_VERSION, "runtime_package": RUNTIME_VERSION}:
        raise Stop("BLOCKED_RUNTIME", "SDK/runtime differ from tested pins; run compatibility tests")
    return v


def quota_public(snapshot):
    """Allowlist: never retain account identity, reset-credit IDs or payment details."""
    keys = ("limitId", "primary", "secondary", "individualLimit", "spendControlReached", "rateLimitReachedType")
    def bucket(b):
        return {k: b.get(k) for k in keys} if b else None
    # Ordinary allowance and each independent bucket retain their own semantics.
    return {"ordinaryUsageAllowed": snapshot.get("ordinaryUsageAllowed"),
            "rateLimits": bucket(snapshot.get("rateLimits")),
            "rateLimitsByLimitId": {k: bucket(v) for k, v in (snapshot.get("rateLimitsByLimitId") or {}).items()}}


def deny_approval(method, _params):
    if method == "item/permissions/requestApproval":
        return {"permissions": {}, "scope": "turn"}
    if method == "item/tool/requestUserInput":
        return {"answers": {}}
    if method == "mcpServer/elicitation/request":
        return {"action": "decline", "content": None}
    return {"decision": "decline"}


class Runtime:
    def __init__(self, cwd, *, inventory_only=False):
        verify_versions()
        self.cwd = str(Path(cwd).resolve())
        self.client = CodexClient(CodexConfig(cwd=self.cwd, experimental_api=False,
                                             config_overrides=BASE_OVERRIDES),
                                  approval_handler=deny_approval)
        self.closed = False
        self.inventory_only = inventory_only
        self.disabled_servers = []
        self.thread_settings = {}

    def __enter__(self):
        self.client.start()
        try:
            self.metadata = dump(self._bounded(self.client.initialize, 30))
            auth = self.rpc("account/read", {"refreshToken": False}).get("account")
            if not auth or auth.get("type") != "chatgpt":
                raise Stop("BLOCKED_AUTH", "Official ChatGPT login required; API billing not permitted")
            config = self.rpc("config/read", {"includeLayers": False}).get("config", {})
            self.native = {k: config.get(k) for k in ("model", "model_reasoning_effort")}
            self.disabled_servers = list((config.get("mcp_servers") or {}).keys())
            self.plugins = list((config.get("plugins") or {}).keys())
            # Bounded pagination for future catalogs.
            response = self.rpc("model/list", {})
            self.catalog = response.get("data", [])
            pages = 0
            while response.get("nextCursor"):
                pages += 1
                if pages > 20:
                    raise Stop("BLOCKED_RUNTIME", "Unexpected model catalog pagination")
                response = self.rpc("model/list", {"cursor": response["nextCursor"]})
                self.catalog.extend(response.get("data", []))
            threading.Thread(target=self._listen, daemon=True).start()
            return self
        except BaseException:
            self.client.close()
            raise

    def __exit__(self, *_):
        self.closed = True
        self.client.close()

    def rpc(self, method, params=None):
        if method not in ALLOWED_METHODS:
            raise Stop("BLOCKED_POLICY", "Non-allowlisted RPC: " + method)
        timeout = (params or {}).get("timeoutMs", 30000) / 1000 + 15
        return self._bounded(lambda: self.client.request(method, params or {}, response_model=RootModel[dict]), timeout).root

    def _bounded(self, call, timeout):
        result = queue.Queue()
        def invoke():
            try: result.put((True, call()))
            except BaseException as e: result.put((False, e))
        threading.Thread(target=invoke, daemon=True).start()
        try: ok, value = result.get(timeout=timeout)
        except queue.Empty:
            self.closed = True
            self.client.close() # Own runtime only; never kill other Codex processes.
            raise Stop("BLOCKED_RUNTIME", "SDK request timed out; runtime closed, checkpoint reconciliation required")
        if not ok: raise value
        return value

    def _listen(self):
        # Drain global notifications; relevant turn events have their own public
        # SDK subscription. Do not retain an unbounded, unconsumed second queue.
        try:
            while not self.closed:
                self.client.next_notification()
        except Exception:
            pass  # Turn subscriptions and RPC calls report their own failures.

    def quota(self):
        try:
            return quota_public(self.rpc("account/rateLimits/read"))
        except Exception:
            return None

    def inventory(self):
        out = {"versions": versions(), "runtime_metadata": self.metadata, "auth_mode": "chatgpt",
               "native": self.native, "models": self.catalog, "quota": self.quota()}
        for method, key, params in (
            ("skills/list", "skills", {"cwds": [self.cwd], "forceReload": True}),
            ("mcpServerStatus/list", "mcp", {}),
            ("plugin/list", "plugins", {"cwds": [self.cwd]}),
        ):
            try:
                data = self.rpc(method, params)
                if key == "skills":
                    data = [{"names": [s["name"] for s in d.get("skills", [])],
                             "error_count": len(d.get("errors", []))} for d in data.get("data", [])]
                elif key == "mcp":
                    data = [{"name": s["name"], "tools": list(s.get("tools", {})),
                             "authStatus": s.get("authStatus")} for s in data.get("data", [])]
                else:
                    data = {"marketplace_count": len(data.get("marketplaces", [])),
                            "load_error_count": len(data.get("marketplaceLoadErrors", []))}
                out[key] = data
            except Exception as e:
                out[key] = {"unknown": type(e).__name__}
        return out

    def worker_config(self):
        cfg = {"features.apps": False, "features.hooks": False, "features.multi_agent": False,
               "features.memories": False, "web_search": "disabled",
               "sandbox_workspace_write.network_access": False,
               "sandbox_workspace_write.writable_roots": []}
        for name in self.disabled_servers:
            cfg[f'mcp_servers.{name}.enabled'] = False
        # Process/thread overrides only. Installed plugins and global settings untouched.
        for name in self.plugins:
            cfg[f'plugins.{name}.enabled'] = False
        return cfg

    def start(self, cwd, selection, instructions, *, read_only=False, resume=None):
        p = {"cwd": str(cwd), "approvalPolicy": "never",
             "sandbox": "read-only" if read_only else "workspace-write",
             "developerInstructions": instructions, "config": self.worker_config()}
        if selection.requested_model:
            p["model"] = selection.requested_model
        if resume:
            p["threadId"] = resume
            r = self.rpc("thread/resume", p)
        else:
            r = self.rpc("thread/start", p)
        tid = r["thread"]["id"]
        self.thread_settings[tid] = {"resolved_model": r.get("model"), "sandbox": r.get("sandbox")}
        return tid

    def read(self, tid):
        return self.rpc("thread/read", {"threadId": tid, "includeTurns": False})

    def interrupt(self, tid, turn):
        return self.rpc("turn/interrupt", {"threadId": tid, "turnId": turn})

    def turn(self, tid, text, selection, *, deadline, should_pause=lambda: False,
             on_event=lambda *_: None, on_start=lambda *_: None, output_schema=None, external=False):
        p = {"threadId": tid, "input": [{"type": "text", "text": text}], "approvalPolicy": "never"}
        if external:
            p["input"] = []
            p["toolOutput"] = {"name": "factory_task", "output": text}
        if selection.requested_model:
            p["model"] = selection.requested_model
        if selection.requested_effort:
            p["effort"] = selection.requested_effort
        if output_schema:
            p["outputSchema"] = output_schema
        inputs = p.pop("input")
        r = self._bounded(lambda: self.client.turn_start(tid, inputs, p), max(1, min(45, deadline-time.time())))
        turn = r.turn.id
        turn_events = queue.Queue()
        def consume():
            try:
                while True:
                    event = self.client.next_turn_notification(turn)
                    data = dump(event.payload) if hasattr(event.payload, "model_dump") else event.payload.params
                    turn_events.put((event.method, data))
                    if event.method == "turn/completed": break
            except Exception as e:
                turn_events.put(("transport/closed", {"error": type(e).__name__}))
            finally:
                self.client.unregister_turn_notifications(turn)
        threading.Thread(target=consume, daemon=True).start()
        on_start(tid, turn)
        result = {"thread_id": tid, "turn_id": turn, "status": "unknown", "usage": None,
                  "effective_model": None, "resolved_model": self.thread_settings.get(tid, {}).get("resolved_model"),
                  "final": None, "commands": [], "compactions": [], "events": []}
        interrupted_at = None
        stop_state = None
        while True:
            if interrupted_at is None and (should_pause() or time.time() >= deadline):
                stop_state = "PAUSED" if should_pause() else "PAUSED_DEADLINE"
                try:
                    self.interrupt(tid, turn)
                except Exception:
                    # Completion can race the interrupt request; await authoritative event.
                    pass
                interrupted_at = time.time()
            if interrupted_at and time.time() - interrupted_at > 15:
                result["status"] = "interrupt_unconfirmed"
                result["stop_state"] = stop_state
                return result
            try:
                method, data = turn_events.get(timeout=.2)
            except queue.Empty:
                continue
            if method == "transport/closed":
                raise Stop("BLOCKED_RUNTIME", "SDK event transport closed")
            if data.get("threadId") != tid:
                continue
            if data.get("turnId") not in (None, turn):
                continue
            # Store lifecycle metadata only; never reasoning, prompts or raw tool output.
            if method in ("turn/started", "turn/completed", "thread/tokenUsage/updated", "model/rerouted", "error"):
                result["events"].append(method)
            if method == "thread/tokenUsage/updated":
                result["usage"] = data.get("tokenUsage")
                on_event(method, data)
            elif method == "model/rerouted":
                result["effective_model"] = data.get("toModel")
            elif method == "item/started" and data.get("item", {}).get("type") == "commandExecution":
                on_event(method, {"threadId": tid, "turnId": turn, "item": {"type": "commandExecution", "id": data["item"]["id"]}})
            elif method == "item/completed":
                item = data.get("item", {})
                if item.get("type") == "agentMessage" and item.get("phase") in (None, "final_answer"):
                    result["final"] = item.get("text")
                elif item.get("type") == "commandExecution":
                    result["commands"].append({"status": item.get("status"), "exit_code": item.get("exitCode")})
                elif item.get("type") == "contextCompaction":
                    result["compactions"].append(item["id"])
            elif method == "turn/completed" and data["turn"]["id"] == turn:
                result["status"] = data["turn"]["status"]
                result["error_code"] = (data["turn"].get("error") or {}).get("codexErrorInfo")
                if stop_state:
                    result["stop_state"] = stop_state
                return result

    def command(self, cwd, argv, *, timeout=60, should_pause=lambda: False):
        """Validation uses Codex's sandbox, never an unrestricted shell fallback."""
        process_id = "factory-" + os.urandom(6).hex()
        result = queue.Queue()
        def run():
            try:
                result.put(self.rpc("command/exec", {
                    "command": argv, "cwd": str(cwd), "timeoutMs": max(1, int(timeout * 1000)),
                    "processId": process_id, "outputBytesCap": 2_000_000,
                    "sandboxPolicy": {"type": "workspaceWrite", "writableRoots": [str(cwd)],
                                      "networkAccess": False},
                }))
            except Exception as e:
                result.put(e)
        threading.Thread(target=run, daemon=True).start()
        end = time.time() + timeout + 10
        while True:
            try:
                r = result.get(timeout=.2)
                if isinstance(r, Exception):
                    raise Stop("BLOCKED_VALIDATION", "Sandbox command failed: " + type(r).__name__)
                return r
            except queue.Empty:
                if should_pause() or time.time() >= end:
                    try:
                        self.rpc("command/exec/terminate", {"processId": process_id})
                    except Exception:
                        pass
                    raise Stop("PAUSED" if should_pause() else "PAUSED_DEADLINE", "Validation interrupted")

    def compact(self, tid, *, deadline, checkpoint, on_event=lambda *_: None):
        if not checkpoint:
            raise Stop("BLOCKED_CONTEXT", "Durable checkpoint required before manual compaction")
        if time.time() >= deadline:
            return {"state": "TIMEOUT", "turn_id": None, "usage": None}
        current = self.read(tid)["thread"]
        if current.get("status", {}).get("type") != "idle":
            raise Stop("BLOCKED_CONTEXT", "Compaction requires an idle thread")
        before = self.rpc("thread/read", {"threadId": tid, "includeTurns": True})["thread"].get("turns", [])
        previous = {t["id"] for t in before}
        if time.time() >= deadline:
            return {"state": "TIMEOUT", "turn_id": None, "usage": None}
        self.rpc("thread/compact/start", {"threadId": tid})
        latest = None
        # SDK 0.157.1 drops unsolicited turn events without a pre-existing turn
        # subscription. Compaction returns no turn ID. Read documented turn state
        # deterministically; no private router fields or LLM polling.
        while time.time() < deadline:
            turns = self.rpc("thread/read", {"threadId": tid, "includeTurns": True})["thread"].get("turns", [])
            for turn in turns:
                if turn["id"] in previous: continue
                latest = turn
                items = [i["id"] for i in turn.get("items", []) if i.get("type") == "contextCompaction"]
                if turn["status"] in ("completed", "failed", "interrupted"):
                    state = ("COMPLETED" if items else "NO_OP") if turn["status"] == "completed" else turn["status"].upper()
                    return {"state": state, "turn_id": turn["id"], "items": items,
                            "evidence": "thread/read persisted turn state", "usage": None}
            time.sleep(.25)
        if latest:
            try: self.interrupt(tid, latest["id"])
            except Exception: pass
        return {"state": "TIMEOUT", "turn_id": latest["id"] if latest else None, "usage": None}

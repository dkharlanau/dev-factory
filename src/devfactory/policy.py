"""Pure policies. Task/model text never becomes configuration or executable argv."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict


class Stop(RuntimeError):
    def __init__(self, state: str, reason: str):
        self.state, self.reason = state, reason
        super().__init__(reason)


@dataclass(frozen=True)
class Selection:
    profile: str
    requested_model: str | None
    requested_effort: str | None
    reason: str
    policy_version: str

    def dict(self):
        return asdict(self)


def choose_model(profile, config, catalog, native, *, baseline=False, high_risk=False):
    default = next((m for m in catalog if m.get("isDefault")), None)
    native_model = native.get("model") or (default or {}).get("model")
    available = {m["model"]: m for m in catalog}
    if not available or native_model not in available:
        raise Stop("NATIVE_HANDOFF", "No verified native/default model in available catalog")
    if baseline:
        return Selection(profile, None, None, "Native model and effort; no routing override", config["policy_version"])
    p = config["profiles"][profile]
    configured = p.get("models")
    if configured is None:
        configured = [p.get("model", "native")]
    if not isinstance(configured, list) or not configured or not all(isinstance(x, str) and x for x in configured):
        raise Stop("BLOCKED_POLICY", f"Profile {profile} must define model or a non-empty models list")
    skipped = []
    model = None
    for candidate in configured:
        resolved = native_model if candidate == "native" else candidate
        info = available.get(resolved)
        if not info or "text" not in info.get("inputModalities", []):
            skipped.append(candidate)
            continue
        model = resolved
        break
    if model is None:
        model = native_model
        info = available[model]
        if "text" not in info.get("inputModalities", []):
            raise Stop("NATIVE_HANDOFF", "Verified native/default model does not declare text input support")
        reason = "Configured model ladder unavailable; verified native fallback"
    elif configured[0] == "native" and model == native_model:
        info = available[model]
        reason = "Owner profile preserves verified native model"
    else:
        info = available[model]
        reason = ("Owner model ladder selected first available candidate after unavailable entries"
                  if skipped else "Owner model ladder selected by task/role profile; verified against live catalog")
    effort = "high" if profile == "review" and high_risk else p.get("effort")
    efforts = [e["reasoningEffort"] for e in info["supportedReasoningEfforts"]]
    if effort not in efforts:
        effort = info["defaultReasoningEffort"]
        reason += "; unsupported effort fell back to catalog default"
    return Selection(profile, model, effort, reason, config["policy_version"])


def classify(task, high_risk_paths):
    risk = task.get("risk", "unknown")
    risk_text = " ".join([str(task.get("category", "")), str(task.get("description", "")), *task.get("paths", [])])
    if re.search(r"auth(?:entication|orization)?|privacy|migration|public.release|database.activation|(?:factory|routing|budget).{0,12}policy", risk_text, re.I):
        risk = "high"
    complexity = task.get("complexity", "unknown")
    if high_risk_paths and any(p.startswith(tuple(high_risk_paths)) for p in task.get("paths", [])):
        risk = "high"
    if risk == "high" or complexity == "high":
        return "deep", risk
    if risk == "low" and complexity == "low" and task.get("verification") == "strong":
        return "fast", risk
    return "standard", risk


def check_quota(snapshot, budget):
    if not snapshot:
        raise Stop("PAUSED_QUOTA", "Account quota unknown; new turns disabled")
    if snapshot.get("ordinaryUsageAllowed") is False:
        raise Stop("PAUSED_QUOTA", "Ordinary subscription usage unavailable")
    bucket = (snapshot.get("rateLimitsByLimitId") or {}).get(budget["quota_bucket"])
    if bucket is None:
        legacy = snapshot.get("rateLimits") or {}
        if legacy.get("limitId") == budget["quota_bucket"]:
            bucket = legacy
    if not bucket:
        raise Stop("PAUSED_QUOTA", "Relevant shared allowance bucket unknown")
    if bucket.get("rateLimitReachedType") or bucket.get("spendControlReached"):
        raise Stop("PAUSED_QUOTA", "Runtime reports shared quota/spend limit")
    windows = [bucket.get(k) for k in ("primary", "secondary", "individualLimit")]
    windows = [w for w in windows if isinstance(w, dict) and w.get("usedPercent") is not None]
    if not windows:
        raise Stop("PAUSED_QUOTA", "Relevant allowance percentage unknown")
    for w in windows:
        if 100 - w["usedPercent"] <= budget["allowance_reserve_percent"]:
            raise Stop("PAUSED_QUOTA", "Shared allowance reserve reached; no model switching")


def check_budget(budget, *, deadline, turns, tokens):
    if time.time() >= deadline:
        raise Stop("PAUSED_DEADLINE", "Execution deadline reached")
    if turns >= budget["max_turns"]:
        raise Stop("PAUSED_BUDGET", "Model turn limit reached")
    if tokens is not None and tokens >= budget["soft_tokens"]:
        raise Stop("PAUSED_BUDGET", "Observable token soft budget reached")


def repair_decision(failures, repairs, escalations, budget, infrastructure=False):
    if infrastructure:
        return "BLOCKED_INFRASTRUCTURE"
    if repairs >= budget["repair_rounds"]:
        return "BLOCKED_REPAIR_LIMIT"
    if failures >= 2 and escalations < budget["escalations"]:
        return "ESCALATE"
    return "REPAIR"


TOKEN_FIELDS = ("inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens",
                "cacheWriteInputTokens", "totalTokens")


class Usage:
    """Cumulative per-thread snapshots, not deltas. Subcategories never add to total."""
    def __init__(self, totals=None):
        self.totals = totals or {}

    def observe(self, thread, usage):
        snapshot = usage.get("total", {})
        previous = self.totals.get(thread, {})
        merged = {}
        for k in TOKEN_FIELDS:
            v, old = snapshot.get(k), previous.get(k)
            merged[k] = old if v is None else max(v, old or 0)
        self.totals[thread] = merged

    def aggregate(self):
        return {k: (sum(t[k] for t in self.totals.values())
                    if self.totals and all(t.get(k) is not None for t in self.totals.values())
                    else None) for k in TOKEN_FIELDS}


def usage_efficiency(total):
    """Derived observability only; never infer price or context occupancy."""
    inputs, cached = total.get("inputTokens"), total.get("cachedInputTokens")
    uncached = max(0, inputs - cached) if inputs is not None and cached is not None else None
    ratio = cached / inputs if inputs not in (None, 0) and cached is not None else None
    return {"uncached_input_tokens": uncached, "cached_input_ratio": ratio}


INJECTION = re.compile(
    r"ignore (?:all |previous |prior )?(?:instructions|policy)|"
    r"(?:read|print|cat|upload|send|expose).{0,35}(?:auth\.json|\.env\b|secrets?|tokens?)|"
    r"(?:disable|bypass|weaken|change|override).{0,35}(?:sandbox|budget|policy|allowance|approval)|"
    r"danger-full-access|factory\.local\.toml|reset --hard", re.I | re.S)


def screen_task(task):
    text = str(task.get("acceptance", "")) + "\n" + str(task.get("description", ""))
    if INJECTION.search(text):
        raise Stop("NATIVE_HANDOFF", "Task requests policy/secret/sandbox changes; owner review required")
    for path in task.get("paths", []):
        if path.startswith(("/", "~")) or ".." in path.split("/") or any(
            x in path.split("/") for x in (".git", ".env", "auth.json", ".factory", ".codex", ".agents")
        ):
            raise Stop("NATIVE_HANDOFF", "Task path escapes permitted code scope")


def integration_gate(policy, evidence):
    if policy.get("merge") or policy.get("deploy"):
        raise Stop("NATIVE_HANDOFF", "MVP never merges or deploys automatically")
    if not policy.get("push") or not policy.get("pull_request"):
        raise Stop("READY_LOCAL", "Remote integration disabled by owner policy")
    for key in ("triggers_reviewed", "spend_reviewed", "owner_restrictions_reviewed", "checks_passed", "review_passed"):
        if evidence.get(key) is not True:
            raise Stop("NATIVE_HANDOFF", "Integration gate missing: " + key)
    if evidence.get("reviewed_sha") != evidence.get("head_sha") or evidence.get("reviewed_base") != evidence.get("base_sha"):
        raise Stop("NATIVE_HANDOFF", "Reviewed HEAD/base changed")

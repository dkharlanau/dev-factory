from __future__ import annotations
import os
import tomllib
from pathlib import Path
from importlib.resources import files
from .policy import Stop


def merge(target, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            merge(target[k], v)
        else:
            target[k] = v
    return target


def load(root: Path, local: Path | None = None):
    config = tomllib.loads(files("devfactory").joinpath("defaults.toml").read_text())
    path = local or Path(os.environ.get("FACTORY_CONFIG", root / "factory.local.toml"))
    if path.exists():
        override = tomllib.loads(path.read_text())
        for name, profile in (override.get("profiles") or {}).items():
            if isinstance(profile, dict) and "model" in profile and "models" in profile:
                raise Stop("BLOCKED_POLICY", f"Profile {name} cannot define both model and models")
            if isinstance(profile, dict) and "model" in profile:
                # Legacy scalar override intentionally replaces the inherited v2 ladder.
                config.get("profiles", {}).get(name, {}).pop("models", None)
        merge(config, override)
    config["root"] = str(root.resolve())
    config["local_config"] = str(path.resolve())
    config["state_dir"] = str(Path(config.get("state_dir", root / ".factory")).expanduser().resolve())
    if config["integration"].get("merge") or config["integration"].get("deploy"):
        raise Stop("BLOCKED_POLICY", "Automatic merge/deploy unavailable in MVP")
    b = config["budget"]
    if not 0 < b["allowance_reserve_percent"] < 100 or not 1 <= b["max_turns"] <= 20:
        raise Stop("BLOCKED_POLICY", "Invalid reserve or per-task turn budget")
    queue_turns = b.get("max_queue_turns", b["max_turns"])
    if not b["max_turns"] <= queue_turns <= 100:
        raise Stop("BLOCKED_POLICY", "Queue turn budget must be >= per-task turns and <= 100")
    if not 0 <= b["repair_rounds"] <= 2 or not 0 <= b["escalations"] <= 1:
        raise Stop("BLOCKED_POLICY", "MVP permits at most two repairs and one escalation")
    if b["deadline_seconds"] <= 0 or b["soft_tokens"] <= 0:
        raise Stop("BLOCKED_POLICY", "Execution limits must be positive")
    if not isinstance(b.get("finish_started_task"), bool):
        raise Stop("BLOCKED_POLICY", "finish_started_task must be boolean")
    batch=config.get("batching",{})
    if not isinstance(batch.get("enabled"),bool) or not 1 <= batch.get("max_tasks",0) <= 10:
        raise Stop("BLOCKED_POLICY", "Batching must be boolean with max_tasks 1..10")
    if not 1 <= batch.get("max_paths",0) <= 100 or not 1 <= batch.get("max_checks",0) <= 20:
        raise Stop("BLOCKED_POLICY", "Batch path/check limits are invalid")
    if not 1000 <= batch.get("max_packet_bytes",0) <= 100000:
        raise Stop("BLOCKED_POLICY", "Batch packet byte limit is invalid")
    ctx=config["context"]
    if not 1 <= ctx.get("navigation_files",0) <= 200 or not 1000 <= ctx.get("failure_log_bytes",0) <= 100000:
        raise Stop("BLOCKED_POLICY", "Context navigation/log limits are invalid")
    if not isinstance(ctx.get("cold_paths"),list) or not all(isinstance(x,str) and x for x in ctx["cold_paths"]):
        raise Stop("BLOCKED_POLICY", "cold_paths must be a list of path prefixes")
    for name, profile in config["profiles"].items():
        models = profile.get("models")
        if models is not None and (not isinstance(models, list) or not models or
                                   not all(isinstance(m, str) and m for m in models)):
            raise Stop("BLOCKED_POLICY", f"Profile {name} has invalid model ladder")
    if b.get("unknown_quota") != "pause" or not config["context"]["native_autocompaction"]:
        raise Stop("BLOCKED_POLICY", "Unknown quota must pause; native autocompaction remains enabled")
    if config["context"].get("manual_compaction"):
        raise Stop("BLOCKED_POLICY", "Automatic Factory compaction is not implemented; retain native autocompaction")
    return config

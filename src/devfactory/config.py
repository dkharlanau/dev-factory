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
        merge(config, tomllib.loads(path.read_text()))
    config["root"] = str(root.resolve())
    config["local_config"] = str(path.resolve())
    config["state_dir"] = str(Path(config.get("state_dir", root / ".factory")).expanduser().resolve())
    if config["integration"].get("merge") or config["integration"].get("deploy"):
        raise Stop("BLOCKED_POLICY", "Automatic merge/deploy unavailable in MVP")
    b = config["budget"]
    if not 0 < b["allowance_reserve_percent"] < 100 or not 1 <= b["max_turns"] <= 20:
        raise Stop("BLOCKED_POLICY", "Invalid reserve or turn budget")
    if not 0 <= b["repair_rounds"] <= 2 or not 0 <= b["escalations"] <= 1:
        raise Stop("BLOCKED_POLICY", "MVP permits at most two repairs and one escalation")
    if b["deadline_seconds"] <= 0 or b["soft_tokens"] <= 0:
        raise Stop("BLOCKED_POLICY", "Execution limits must be positive")
    if b.get("unknown_quota") != "pause" or not config["context"]["native_autocompaction"]:
        raise Stop("BLOCKED_POLICY", "Unknown quota must pause; native autocompaction remains enabled")
    return config

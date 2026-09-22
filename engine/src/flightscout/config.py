"""CLI configuration stored at ~/.config/flightscout/config.json. Environment
variables win over the file (FLIGHTSCOUT_API_URL, FLIGHTSCOUT_TOKEN,
FLIGHTSCOUT_CURRENCY, FLIGHTSCOUT_TRACKER_KEY)."""

from __future__ import annotations

import json
import os
from pathlib import Path

PATH = Path(os.environ.get("FLIGHTSCOUT_CONFIG", Path.home() / ".config" / "flightscout" / "config.json"))


def load() -> dict:
    try:
        cfg = json.loads(PATH.read_text())
    except (OSError, ValueError):
        cfg = {}
    env = {
        "api_url": os.environ.get("FLIGHTSCOUT_API_URL"),
        "token": os.environ.get("FLIGHTSCOUT_TOKEN"),
        "currency": os.environ.get("FLIGHTSCOUT_CURRENCY"),
        "tracker_key": os.environ.get("FLIGHTSCOUT_TRACKER_KEY"),
    }
    cfg.update({k: v for k, v in env.items() if v})
    cfg.setdefault("currency", "USD")
    return cfg


def save(**values) -> dict:
    cfg = load()
    cfg.update({k: v for k, v in values.items() if v is not None})
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(cfg, indent=2))
    PATH.chmod(0o600)
    return cfg

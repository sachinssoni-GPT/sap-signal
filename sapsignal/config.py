"""Configuration loading. Secrets come from .env, everything else from config.yaml."""
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent   # where config.yaml and .env live
ROOT = PROJECT_DIR                                       # base for data/content/reports (tests override this)
load_dotenv(PROJECT_DIR / ".env")


@lru_cache(maxsize=1)
def get_config() -> dict:
    with open(PROJECT_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def path_for(key: str) -> Path:
    p = ROOT / get_config()["paths"][key]
    p.mkdir(parents=True, exist_ok=True) if key != "db" else p.parent.mkdir(parents=True, exist_ok=True)
    return p


def today_iso() -> str:
    """Edition date in the publication's timezone (GitHub runners are UTC; you are not)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = get_config().get("publication", {}).get("timezone", "Asia/Kolkata")
    return datetime.now(ZoneInfo(tz)).date().isoformat()

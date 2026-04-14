from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PRODUCTS_PATH = BASE_DIR / "products.yaml"
DEFAULT_DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "market_radar.db"


def load_products(path: Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_PRODUCTS_PATH
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data

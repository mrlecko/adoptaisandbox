"""
Dataset registry helpers for agent-server.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def load_registry(datasets_dir: str) -> Dict[str, Any]:
    registry_path = Path(datasets_dir) / "registry.json"
    if not registry_path.exists():
        raise FileNotFoundError(f"Dataset registry not found: {registry_path}")
    return json.loads(registry_path.read_text())


def get_dataset_by_id(registry: Dict[str, Any], dataset_id: str) -> Dict[str, Any]:
    for ds in registry.get("datasets", []):
        if ds["id"] == dataset_id:
            return ds
    raise KeyError(f"Unknown dataset_id: {dataset_id}")

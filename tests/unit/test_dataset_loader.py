from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.datasets import get_dataset_by_id, load_registry  # noqa: E402


def test_load_registry_reads_datasets():
    registry = load_registry(str(Path(__file__).parent.parent.parent / "datasets"))
    assert "datasets" in registry
    assert {d["id"] for d in registry["datasets"]} == {"ecommerce", "support", "sensors"}


def test_get_dataset_by_id_success():
    registry = load_registry(str(Path(__file__).parent.parent.parent / "datasets"))
    ds = get_dataset_by_id(registry, "support")
    assert ds["id"] == "support"
    assert ds["files"][0]["name"] == "tickets.csv"


def test_get_dataset_by_id_missing_raises():
    registry = load_registry(str(Path(__file__).parent.parent.parent / "datasets"))
    with pytest.raises(KeyError):
        get_dataset_by_id(registry, "missing")


def test_load_registry_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_registry(str(tmp_path))

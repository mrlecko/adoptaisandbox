from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.storage.capsules import get_capsule, init_capsule_db, insert_capsule  # noqa: E402


def test_capsule_roundtrip_and_indexes(tmp_path):
    db_path = tmp_path / "capsules.db"
    init_capsule_db(str(db_path))

    insert_capsule(
        str(db_path),
        {
            "run_id": "r1",
            "created_at": "2026-02-03T00:00:00+00:00",
            "dataset_id": "support",
            "dataset_version_hash": "abc",
            "question": "q",
            "query_mode": "python",
            "plan_json": None,
            "compiled_sql": None,
            "python_code": "result = 1",
            "status": "succeeded",
            "result_json": {"rows": [[1]], "columns": ["value"]},
            "error_json": None,
            "exec_time_ms": 12,
        },
    )

    got = get_capsule(str(db_path), "r1")
    assert got is not None
    assert got["query_mode"] == "python"
    assert got["python_code"] == "result = 1"
    assert got["result_json"]["rows"] == [[1]]

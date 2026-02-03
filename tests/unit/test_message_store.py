from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.storage.messages import SQLiteMessageStore, create_message_store  # noqa: E402


def test_sqlite_message_store_roundtrip(tmp_path):
    db_path = tmp_path / "capsules.db"
    store = SQLiteMessageStore(str(db_path))
    store.initialize()

    store.append_message(
        thread_id="t1",
        role="user",
        content="hello",
        dataset_id="support",
        run_id="r1",
    )
    store.append_message(
        thread_id="t1",
        role="assistant",
        content="hi there",
        dataset_id="support",
        run_id="r1",
        metadata={"query_mode": "chat"},
    )

    messages = store.get_messages(thread_id="t1", limit=10)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["metadata"] == {"query_mode": "chat"}


def test_create_message_store_sqlite(tmp_path):
    store = create_message_store("sqlite", str(tmp_path / "capsules.db"))
    assert isinstance(store, SQLiteMessageStore)


def test_create_message_store_unknown_provider_raises(tmp_path):
    with pytest.raises(ValueError, match="Unsupported message storage provider"):
        create_message_store("redis", str(tmp_path / "capsules.db"))

"""Unit tests for MLflow tracing configuration."""

from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.main import (  # noqa: E402
    Settings,
    _configure_mlflow_tracing,
    _run_with_mlflow_session_trace,
)


def test_configure_mlflow_tracing_noop_when_disabled(monkeypatch):
    settings = Settings(mlflow_openai_autolog=False, mlflow_tracking_uri=None)
    _configure_mlflow_tracing(settings)


def test_configure_mlflow_tracing_noop_without_uri(monkeypatch):
    settings = Settings(mlflow_openai_autolog=True, mlflow_tracking_uri=None)
    _configure_mlflow_tracing(settings)


def test_configure_mlflow_tracing_enables_openai_autolog(monkeypatch):
    calls = []

    class _FakeOpenAI:
        def autolog(self):
            calls.append(("openai.autolog", None))

    fake_mlflow = SimpleNamespace(
        set_tracking_uri=lambda uri: calls.append(("set_tracking_uri", uri)),
        set_experiment=lambda name: calls.append(("set_experiment", name)),
        openai=_FakeOpenAI(),
    )
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)

    settings = Settings(
        mlflow_openai_autolog=True,
        mlflow_tracking_uri="http://localhost:5000",
        mlflow_experiment_name="CSV Analyst Agent",
    )
    _configure_mlflow_tracing(settings)

    assert ("set_tracking_uri", "http://localhost:5000") in calls
    assert ("set_experiment", "CSV Analyst Agent") in calls
    assert ("openai.autolog", None) in calls


def test_run_with_mlflow_session_trace_noop_without_uri():
    settings = Settings(mlflow_openai_autolog=False, mlflow_tracking_uri=None)
    assert (
        _run_with_mlflow_session_trace(
            settings=settings,
            span_name="chat.turn",
            user_id="user-1",
            session_id="thread-1",
            metadata={"dataset_id": "support"},
            trace_input={"message": "hello"},
            fn=lambda: "ok",
        )
        == "ok"
    )


def test_run_with_mlflow_session_trace_sets_user_session_metadata(monkeypatch):
    calls = {"trace_names": [], "metadata": [], "inputs": []}

    def _trace(*, name):
        def _decorator(fn):
            def _wrapped(*args, **kwargs):
                calls["trace_names"].append(name)
                calls["inputs"].append(args[0] if args else None)
                return fn(*args, **kwargs)

            return _wrapped

        return _decorator

    def _update_current_trace(*, metadata):
        calls["metadata"].append(metadata)

    fake_mlflow = SimpleNamespace(
        trace=_trace,
        update_current_trace=_update_current_trace,
    )
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)

    settings = Settings(
        mlflow_openai_autolog=False,
        mlflow_tracking_uri="http://localhost:5000",
    )
    result = _run_with_mlflow_session_trace(
        settings=settings,
        span_name="chat.turn",
        user_id="user-123",
        session_id="thread-abc",
        metadata={"dataset_id": "ecommerce"},
        trace_input={"message": "top 10 products"},
        fn=lambda: {"status": "ok"},
    )

    assert result == {"status": "ok"}
    assert calls["trace_names"] == ["chat.turn"]
    assert calls["metadata"] == [
        {
            "mlflow.trace.user": "user-123",
            "mlflow.trace.session": "thread-abc",
            "dataset_id": "ecommerce",
        }
    ]
    assert calls["inputs"] == [{"message": "top 10 products"}]

"""Unit tests for MLflow tracing configuration."""

from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.main import Settings, _configure_mlflow_tracing  # noqa: E402


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

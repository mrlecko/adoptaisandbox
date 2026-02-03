from pathlib import Path


def test_required_libs_importable():
    import docker  # noqa: F401
    import kubernetes  # noqa: F401
    import langchain  # noqa: F401


def test_scaffold_files_exist():
    assert Path("agent-server/Dockerfile").exists()
    assert Path("runner/Dockerfile").exists()
    assert Path("ui/Dockerfile").exists()
    assert Path("docker-compose.yml").exists()

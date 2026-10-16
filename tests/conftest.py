import pytest


@pytest.fixture(autouse=True)
def isolated_generation_settings(tmp_path, monkeypatch):
    """Tests never read or create your real generation.json (so they never start WanGP)."""
    from autoedit import generation
    monkeypatch.setattr(generation, "PROJECT_DIR", tmp_path / "project")

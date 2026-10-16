import pytest


@pytest.fixture(autouse=True)
def isolated_generation_settings(tmp_path, monkeypatch):
    """Tests never read or create your real generation.json (so they never start WanGP)."""
    from autoedit import generation
    monkeypatch.setattr(generation, "PROJECT_DIR", tmp_path / "project")


@pytest.fixture(autouse=True)
def no_stock_keys(monkeypatch):
    """Tests never search Pexels/Pixabay with your real keys (set empty, so .env is not read)."""
    monkeypatch.setenv("PEXELS_API_KEY", "")
    monkeypatch.setenv("PIXABAY_API_KEY", "")

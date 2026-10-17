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


@pytest.fixture(autouse=True)
def no_default_tracking_models(tmp_path, monkeypatch):
    """Tests never pick up tracking model files you downloaded into models/tracking/."""
    from autoedit import tracking
    monkeypatch.setattr(tracking, "MODEL_DIR", tmp_path / "no-tracking-models")


@pytest.fixture(scope="session", autouse=True)
def graphics_cache(tmp_path_factory):
    """Drawn graphics are cached for the whole test session (and never in your real work folder)."""
    import os
    folder = tmp_path_factory.mktemp("graphics-cache")
    os.environ["AUTOEDIT_GRAPHICS_CACHE"] = str(folder)
    yield folder
    os.environ.pop("AUTOEDIT_GRAPHICS_CACHE", None)

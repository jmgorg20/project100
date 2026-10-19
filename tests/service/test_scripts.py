"""The operator scripts: the load test (against a real HTTP server) and the no-model-weights check."""

import pytest
import requests

from scripts import check_no_weights, loadtest
from tests.service.helpers import ADMIN
from tests.service.test_worker import Server


@pytest.fixture
def server(settings):
    with Server(settings) as s:
        yield s


def test_load_test_reports_latency_and_errors(server):
    r = requests.post(server.url + "/v1/admin/clients", json={"name": "load", "rate_per_minute": 100_000},
                      headers={"Authorization": f"Bearer {ADMIN}"}, timeout=30)
    key = r.json()["api_key"]
    report = loadtest.run(server.url, "read", users=3, seconds=1.5, key=key)
    me = report["results"]["GET /v1/me"]
    assert me["requests"] > 3 and me["codes"] == {"200": me["requests"]} and me["p95_ms"] >= me["p50_ms"] > 0
    report = loadtest.run(server.url, "upload", users=2, seconds=1.5, key=key, file_kb=64)
    assert report["results"]["POST /v1/uploads"]["codes"].get("201")
    assert report["results"]["PUT chunk"]["error_rate"] == 0
    bad = loadtest.run(server.url, "read", users=1, seconds=0.5, key="ak_wrong")
    assert bad["results"]["GET /v1/me"]["error_rate"] == 1


def test_load_test_only_on_your_own_servers(capsys):
    with pytest.raises(SystemExit):
        loadtest.main(["--url", "https://someone-else.example", "--seconds", "1"])
    assert "--i-own-this" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        loadtest.main(["--url", "http://127.0.0.1:1", "--scenario", "read"])        # needs a key
    assert loadtest.percentile([1, 2, 3, 4], 50) == 2.5 and loadtest.percentile([], 50) is None


def test_the_repository_has_no_model_weights():
    assert check_no_weights.check() == []


def test_the_weights_check_finds_them(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "whisper.safetensors").write_bytes(b"x")
    (tmp_path / "big.mp4").write_bytes(b"\0" * (16 * 1024 * 1024))
    (tmp_path / "requirements-worker.txt").write_text("requests>=2\nfaster-whisper==1.0  # local\ntorch\n")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "Dockerfile.worker").write_text("RUN curl -O https://huggingface.co/x/model.gguf\nCOPY . /app\n")
    problems = "\n".join(check_no_weights.check(tmp_path))
    for expected in ("whisper.safetensors", "big.mp4", "faster-whisper", "torch", "huggingface.co", "copies the models"):
        assert expected in problems, expected

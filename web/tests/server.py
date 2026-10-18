"""The real service for the web app's browser tests: the API (SQLite in a temporary folder, emails
written to DATA/outbox), serving the built app at /app/, and a real worker agent pulling jobs over
HTTP and running the stand-in engine (tests/service/fake_engine.py, with captions).

    python web/tests/server.py --port 4180 --data /tmp/web-test

Not for production: development settings, open sign-up, plain http on 127.0.0.1.
"""

import argparse
import os
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=4180)
    p.add_argument("--data", required=True)
    a = p.parse_args()
    data = Path(a.data)
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True)

    import uvicorn

    from service import jobqueue
    from service.api import create_app
    from service.settings import Settings
    from service.worker import Agent

    url = f"http://127.0.0.1:{a.port}"
    settings = Settings(env="development", data_dir=str(data), secret_key="w" * 40, admin_token="a" * 40,
                        public_url=url, signup_mode="open", password_cost=10, monthly_minutes=60.0, signups_per_ip_hour=1000,
                        logins_per_ip_minute=1000, billing="on", billing_provider="fake",
                        lease_seconds=30, claim_wait_seconds=1, chunk_mb=1, log_json=False, web_dir=str(ROOT / "web" / "dist"))
    app = create_app(settings)
    with app.state.db.tx() as t:
        worker = jobqueue.create_worker(t, settings, "web-test", ["cpu"])

    os.environ["AUTOEDIT_FAKE_ENGINE_CAPTIONS"] = "1"
    os.environ["AUTOEDIT_ENGINE_VERSION"] = "web-test"

    def work():
        while not getattr(server, "started", False):
            time.sleep(0.1)
        agent = Agent(url, worker["token"], app.state.public_key, ["cpu"], data / "work", allow_http=True, wait=1,
                      log=lambda *x: None, engine_cmd=[sys.executable, str(ROOT / "tests" / "service" / "fake_engine.py")])
        agent.run_forever()

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=a.port, log_level="warning"))
    threading.Thread(target=work, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()

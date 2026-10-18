"""The headless service: the integration API every client uses (the partner project, the SaaS
website, future projects). One codebase and one engine (autoedit/); this package only adds the
API, the job queue, client management, uploads, webhooks and the worker agent.

    api.py       the HTTP API (FastAPI): clients, workers, admin, files
    db.py        the database (Postgres in production, SQLite for development and tests)
    jobqueue.py  the durable job queue (leases, retries, time limits, channels)
    worker.py    the worker agent: pulls jobs over HTTPS (no inbound ports), runs the engine
    admin_cli.py `python editor.py service-admin ...`

See docs/service.md.
"""

SERVICE_VERSION = "1.0.0"

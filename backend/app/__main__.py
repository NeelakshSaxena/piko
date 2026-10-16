"""`python -m app` — refuses a non-loopback bind unless explicitly allowed (AGENTS.md rule 15)."""

import logging
import sys

import uvicorn

from app.core.config import LOOPBACK_HOSTS, get_settings
from app.main import create_app


def main() -> int:
    settings = get_settings()
    if settings.bind_host not in LOOPBACK_HOSTS and not settings.allow_public_bind:
        print(
            "refusing to bind to a non-loopback address; set PIKO_ALLOW_PUBLIC_BIND=true only "
            "behind a TLS-terminating reverse proxy (see docs/SELF_HOSTING.md)",
            file=sys.stderr,
        )
        return 1
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    # proxy_headers=False: X-Forwarded-For must not choose the client IP used by rate limits.
    uvicorn.run(
        create_app(settings),
        host=settings.bind_host,
        port=settings.port,
        access_log=False,
        proxy_headers=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""`python -m app` entry point — the only path that honors HOST/PORT settings.

The documented `uvicorn app.main:app` command does not read `HOST`/`PORT`; run
via `python -m app` to bind `settings.host`/`settings.port`.
"""

import uvicorn

from app.config import get_settings


def main() -> None:
    """Run the app under uvicorn, binding the configured host and port."""
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()

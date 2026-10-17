"""Entrypoint for a serverless host (Vercel's FastAPI support looks for `app` in `index.py`).

Everything else about the application is unchanged: this only (1) turns secret environment variables into
the key files the application reads (`app/deploy_env.py`) and (2) builds the app from the environment.
Local development and self-hosting use `python -m app` instead and never touch this file.
"""

import os
import tempfile
from pathlib import Path

from app.deploy_env import materialize_secret_files

materialize_secret_files(os.environ, Path(tempfile.mkdtemp(prefix="piko-secrets-")))

from app.main import create_app

app = create_app()

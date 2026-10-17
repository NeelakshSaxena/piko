"""Entrypoint for Vercel Serverless Function (Vercel looks for serverless functions in `api/`).

Everything else about the application is unchanged: this only (1) turns secret environment variables into
the key files the application reads (`app/deploy_env.py`) and (2) builds the app from the environment.
Local development and self-hosting use `python -m app` instead.
"""

import os
import sys
import tempfile
from pathlib import Path

# Ensure backend root is on sys.path
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.deploy_env import materialize_secret_files

materialize_secret_files(os.environ, Path(tempfile.mkdtemp(prefix="piko-secrets-")))

from app.main import create_app

app = create_app()

"""Entry point for running kernel directly: python -m kernel"""

import os

import uvicorn

from kernel.main import create_app

app = create_app()
uvicorn.run(
    app,
    host=os.environ.get("KALI_HOST", "127.0.0.1"),
    port=int(os.environ.get("KALI_PORT", "3005")),
)

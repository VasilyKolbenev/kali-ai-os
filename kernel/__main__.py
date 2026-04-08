"""Entry point for running kernel directly: python -m kernel"""

import uvicorn

from kernel.main import create_app

app = create_app()
uvicorn.run(app, host="127.0.0.1", port=8000)

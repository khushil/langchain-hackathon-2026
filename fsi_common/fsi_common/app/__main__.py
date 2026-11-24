"""Serve the application: ``python -m fsi_common.app``."""

import uvicorn

from fsi_common.app.app import create_app
from fsi_common.app.config import AppConfig


def main() -> None:
    """Start the application on the host and port the environment names."""
    config = AppConfig.from_env()
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()

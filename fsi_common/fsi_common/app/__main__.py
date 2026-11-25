"""Serve the application: ``python -m fsi_common.app``."""

import uvicorn

from fsi_common.app.app import create_app
from fsi_common.app.children import StateLayoutError, check_single_topic_layout
from fsi_common.app.config import REPOSITORY_ROOT, AppConfig, built_topic_folders
from fsi_common.app.shell import create_shell


def main() -> None:
    """Start the application on the host and port the environment names.

    One topic is served in this process. Two or more are served by a shell with each topic in a
    process of its own, because topics keep the starter's package names, which cannot share one.
    A state folder laid out for the other case is refused, with nothing written.
    """
    config = AppConfig.from_env()
    try:
        if len(config.topic_folders) > 1:
            app = create_shell(config)
        else:
            if config.topic_folders:
                others = [f.resolve().name for f in built_topic_folders(REPOSITORY_ROOT)]
                check_single_topic_layout(config.state_dir, config.topic_folders[0], others)
            app = create_app(config)
    except StateLayoutError as exc:
        raise SystemExit(str(exc)) from exc
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()

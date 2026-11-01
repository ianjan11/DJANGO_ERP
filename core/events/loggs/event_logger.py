import logging


logger = logging.getLogger("core.events.system")


# Optional console formatting
if not logger.handlers:

    handler = logging.StreamHandler()

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s "
        "[%(name)s] %(message)s"
    )

    handler.setFormatter(formatter)

    logger.addHandler(handler)

    logger.setLevel(logging.INFO)
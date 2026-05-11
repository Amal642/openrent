import logging
import os
from logging.handlers import (
    TimedRotatingFileHandler
)


LOG_DIR = "logs"

os.makedirs(
    LOG_DIR,
    exist_ok=True
)

file_handler = (
    TimedRotatingFileHandler(

        f"{LOG_DIR}/openrent.log",

        when="midnight",

        interval=1,

        backupCount=14
        )
    )

logging.basicConfig(

    level=logging.INFO,

    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),

    

    handlers=[

    file_handler,

    logging.StreamHandler()
    ]
)


logger = logging.getLogger(
    "openrent-agent"
)
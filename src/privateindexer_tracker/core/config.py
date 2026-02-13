import os

from privateindexer_tracker.core.logger import log

APP_VERSION = "1.3.2"

ANNOUNCE_INTERVAL = int(os.getenv("ANNOUNCE_INTERVAL", 900))
ANNOUNCE_JITTER_PERCENT = int(os.getenv("ANNOUNCE_JITTER_PERCENT", 15))

PEER_TIMEOUT = int(os.getenv("PEER_TIMEOUT", 1800))

HIGH_LATECY_THRESHOLD = int(os.getenv("HIGH_LATECY_THRESHOLD", 250))

REDIS_HOST = os.getenv("REDIS_HOST")

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQL_USER", "privateindexer")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "privateindexer")
MYSQL_DB = os.getenv("MYSQL_DB", "privateindexer")

MYSQL_MAX_RETY = 5
MYSQL_RETRY_BACKOFF = 0.2


def validate_environment():
    """
    Check environment variables for validity and exit on errors
    """
    log.info("[CONFIG] Validating environment")

    # ensure Redis server host is set
    if not REDIS_HOST:
        log.critical(f"[CONFIG] No Redis server host set")
        exit(1)

    # ensure MySQL host is set
    if not MYSQL_HOST:
        log.critical(f"[CONFIG] No MySQL server host set")
        exit(1)

    log.info("[CONFIG] Environment is valid")

"""Run one or more independent worker processes: python -m services.ingestion.worker."""

import logging
import signal
import threading

from services.ingestion.jobs import process_next
from shared.db import get_pg_conn

log = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO)
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            with get_pg_conn(autocommit=True) as conn:
                while not stopped.is_set():
                    if not process_next(conn):
                        stopped.wait(1)
        except Exception:
            log.exception("Worker connection failed; reconnecting")
            stopped.wait(2)


if __name__ == "__main__":
    main()

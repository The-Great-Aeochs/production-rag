"""Ingestion trigger endpoint."""

import threading
from pathlib import Path

from fastapi import APIRouter

from services.ingestion.bulk_runner import run

router = APIRouter(tags=["ingest"])


@router.post("/ingest")
def trigger_ingestion(directory: str = "./documents"):
    """Trigger bulk ingestion in a background thread."""
    doc_dir = Path(directory)
    if not doc_dir.is_dir():
        return {"error": f"Not a directory: {directory}"}, 400

    thread = threading.Thread(target=run, args=(doc_dir,), daemon=True)
    thread.start()

    return {"status": "ingestion_started", "directory": directory}

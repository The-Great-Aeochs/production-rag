"""Seed only the curated public fixture corpus, then enqueue ingestion."""

import shutil
from importlib.resources import files

from services.ingestion.jobs import enqueue, resolve_directory
from shared.config import settings
from shared.db import get_pg_conn


def main():
    if not settings.demo_corpus_id.startswith("public-"):
        raise ValueError("Demo seeding requires a dedicated public- corpus")
    root = settings.ingest_root / settings.demo_corpus_id
    root.mkdir(parents=True, exist_ok=True)
    root = resolve_directory(".", settings.demo_corpus_id)
    for source in files("services.eval").joinpath("fixtures/corpus").iterdir():
        if source.name.endswith(".md"):
            shutil.copyfile(str(source), root / source.name)
    with get_pg_conn(autocommit=True) as conn:
        print(enqueue(conn, ".", settings.demo_corpus_id))


if __name__ == "__main__":
    main()

"""Apply ordered, transactional schema changes: python -m scripts.migrate."""

from pathlib import Path

from shared.db import get_pg_conn

ROOT = Path(__file__).resolve().parents[1]


def migrate() -> None:
    with get_pg_conn(autocommit=True) as conn:
        # Serialize concurrent releases, including the migration table creation.
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(782146593)")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)")
            migrations = [("001_initial", ROOT / "services/ingestion/init.sql")]
            migrations.extend((p.stem, p) for p in sorted((ROOT / "migrations").glob("*.sql")))
            for version, path in migrations:
                if conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=%s", (version,)
                ).fetchone():
                    continue
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations VALUES (%s)", (version,))
                print(f"Applied {version}")


if __name__ == "__main__":
    migrate()

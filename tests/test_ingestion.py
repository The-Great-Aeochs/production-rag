from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from services.ingestion.jobs import resolve_directory
from shared.config import Settings, settings


def test_production_configuration_rejects_missing_secrets():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", api_keys={})


def test_configuration_rejects_invalid_pool_and_chunk_limits():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, pg_pool_min_size=20, pg_pool_max_size=2)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, chunk_min_tokens=1024, chunk_max_tokens=10)


def test_corpus_and_admin_credentials_must_differ():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_keys={"x" * 40: "alpha"}, admin_api_key="x" * 40)


def test_directory_is_confined_to_entire_corpus(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ingest_root", tmp_path)
    root = tmp_path / "alpha"
    root.mkdir()
    (root / "nested").mkdir()
    assert resolve_directory(".", "alpha") == root
    for path in ["..", "nested", "/etc"]:
        with pytest.raises(ValueError):
            resolve_directory(path, "alpha")
    with pytest.raises(ValueError):
        resolve_directory(".", "../alpha")


def test_source_symlinks_cannot_read_outside_corpus(monkeypatch, tmp_path):
    from services.ingestion.bulk_runner import scan_directory

    root = tmp_path / "alpha"
    root.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("secret")
    (root / "link.md").symlink_to(secret)
    with pytest.raises(ValueError):
        scan_directory(root)


def test_document_limits_are_enforced_before_reading(monkeypatch, tmp_path):
    from services.ingestion.bulk_runner import scan_directory

    monkeypatch.setattr(settings, "max_document_bytes", 3)
    (tmp_path / "large.md").write_text("too large")
    with pytest.raises(ValueError):
        scan_directory(tmp_path)


def test_diff_is_corpus_scoped_and_pending_writes_are_retried():
    from services.ingestion.bulk_runner import diff_against_db, pipeline_version

    conn = Mock()
    conn.execute.return_value.fetchall.return_value = [
        ("unchanged.md", "hash", "ready", pipeline_version()),
        ("pending.md", "hash", "pending", pipeline_version()),
        ("old-model.md", "hash", "ready", "outdated-pipeline"),
        ("removed.md", "hash", "ready", pipeline_version()),
    ]
    new, changed, deleted = diff_against_db(
        {"unchanged.md": "hash", "pending.md": "hash", "old-model.md": "hash", "new.md": "hash"},
        conn,
        "alpha",
    )
    assert new == ["new.md"]
    assert changed == ["pending.md", "old-model.md"]
    assert deleted == ["removed.md"]
    assert conn.execute.call_args.args[1] == ("alpha",)


def test_eval_quality_gate_rejects_empty_missing_and_nan_metrics():
    from services.eval.metrics import quality_failures

    assert quality_failures({}, "retrieval")
    assert quality_failures(
        {"total_cases": 2, "hit_rate_at_k": float("nan"), "mrr": 1}, "retrieval"
    )
    assert not quality_failures({"total_cases": 2, "hit_rate_at_k": 1, "mrr": 1}, "retrieval")
    assert quality_failures({"total_cases": 2, "hit_rate_at_k": 1, "mrr": 1}, "e2e")


def test_answers_with_no_citations_do_not_get_perfect_citation_scores(chunk):
    from services.eval.metrics import citation_accuracy

    assert citation_accuracy("Uncited answer", [chunk]) == 0

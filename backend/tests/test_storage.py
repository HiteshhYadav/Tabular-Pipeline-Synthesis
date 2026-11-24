"""Persistence and the TTL sweeper."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import storage
from app.config import settings


def make_dataset(tmp_path: Path, name: str = "churn.csv"):
    stored = tmp_path / "stored.csv"
    stored.write_text("a,b\n1,2\n")
    storage.init_db()
    return storage.insert_dataset(name, stored, 1, 2, ["a", "b"]), stored


def test_insert_and_read_back(tmp_path):
    response, _ = make_dataset(tmp_path)
    row = storage.get_dataset(response.dataset_id)
    assert row is not None
    assert row["filename"] == "churn.csv"
    assert row["state"] == "pending"


def test_wal_is_enabled(tmp_path):
    """WAL lets the hourly sweeper write while requests read."""
    storage.init_db()
    with storage.connect() as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_unknown_id_reads_as_none(tmp_path):
    storage.init_db()
    assert storage.get_dataset("00000000-0000-4000-8000-000000000000") is None


def test_sweep_leaves_fresh_datasets_alone(tmp_path):
    response, stored = make_dataset(tmp_path)
    assert storage.sweep_expired() == 0
    assert storage.get_dataset(response.dataset_id) is not None
    assert stored.exists()


def test_sweep_deletes_expired_rows_and_their_files(tmp_path):
    response, stored = make_dataset(tmp_path)

    stale = (datetime.now(UTC) - timedelta(hours=settings.dataset_ttl_hours + 1)).isoformat()
    with storage.connect() as connection:
        connection.execute(
            "UPDATE datasets SET created_at = ? WHERE id = ?", (stale, response.dataset_id)
        )

    assert storage.sweep_expired() == 1
    assert storage.get_dataset(response.dataset_id) is None
    assert not stored.exists(), "row went but the file was orphaned on disk"


def test_sweep_survives_a_missing_file(tmp_path):
    """A file deleted out from under us must not stop the sweep, or one bad row
    keeps every later expiry alive forever."""
    response, stored = make_dataset(tmp_path)
    stored.unlink()

    stale = (datetime.now(UTC) - timedelta(hours=settings.dataset_ttl_hours + 1)).isoformat()
    with storage.connect() as connection:
        connection.execute(
            "UPDATE datasets SET created_at = ? WHERE id = ?", (stale, response.dataset_id)
        )

    assert storage.sweep_expired() == 1
    assert storage.get_dataset(response.dataset_id) is None


def test_orphan_files_are_reclaimed(tmp_path):
    """A file written before an insert that never happened. Nothing references
    it, so the row-driven sweep cannot see it and it would live forever."""
    uploads = Path(settings.upload_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    orphan = uploads / "abandoned.csv"
    orphan.write_text("a,b\n1,2\n")

    stale = (datetime.now(UTC) - timedelta(hours=settings.dataset_ttl_hours + 1)).timestamp()
    os.utime(orphan, (stale, stale))

    storage.init_db()
    assert storage.sweep_orphan_files() == 1
    assert not orphan.exists()


def test_orphan_sweep_spares_referenced_and_recent_files(tmp_path):
    """An upload being written right now must never look like an orphan."""
    uploads = Path(settings.upload_dir)
    uploads.mkdir(parents=True, exist_ok=True)

    referenced = uploads / "referenced.csv"
    referenced.write_text("a,b\n1,2\n")
    storage.init_db()
    storage.insert_dataset("keep.csv", referenced, 1, 2, ["a", "b"])
    stale = (datetime.now(UTC) - timedelta(hours=settings.dataset_ttl_hours + 1)).timestamp()
    os.utime(referenced, (stale, stale))

    fresh = uploads / "in-flight.csv"
    fresh.write_text("a,b\n1,2\n")

    assert storage.sweep_orphan_files() == 0
    assert referenced.exists()
    assert fresh.exists()


def test_schema_is_idempotent(tmp_path):
    """init_db runs on every boot, so it must tolerate an existing database."""
    storage.init_db()
    storage.init_db()
    with storage.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "datasets" in tables


def test_filename_is_stored_as_data_never_used_as_a_path(tmp_path):
    """A traversal attempt in the filename is inert because the stored path is
    chosen by us, not derived from what the user sent."""
    response, stored = make_dataset(tmp_path, name="../../etc/passwd")
    row = storage.get_dataset(response.dataset_id)
    assert row["filename"] == "../../etc/passwd"
    assert Path(row["stored_path"]) == stored
    assert isinstance(row, sqlite3.Row)


def test_sweep_removes_rows_that_belong_to_an_expired_dataset(tmp_path):
    """generations carry a full profile_json; the TTL promise covers it too."""
    response, _ = make_dataset(tmp_path)
    dataset_id = response.dataset_id
    storage.insert_generation(
        dataset_id=dataset_id,
        attempt=1,
        state="success",
        provider="stub",
        model="m",
        profile_json="{}",
        result_json="{}",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1,
        error_code=None,
        error_message=None,
    )
    pipeline_id = storage.save_pipeline(dataset_id, "{}", [])
    storage.insert_run(dataset_id, pipeline_id, "run-1", "{}")

    stale = (datetime.now(UTC) - timedelta(hours=settings.dataset_ttl_hours + 1)).isoformat()
    with storage.connect() as connection:
        connection.execute("UPDATE datasets SET created_at = ? WHERE id = ?", (stale, dataset_id))

    assert storage.sweep_expired() == 1
    assert storage.get_generations(dataset_id) == []
    assert storage.get_pipeline(dataset_id) is None
    assert storage.get_latest_run(dataset_id, pipeline_id) is None


def test_saving_a_profile_discards_the_pipeline_and_its_runs(tmp_path):
    response, _ = make_dataset(tmp_path)
    pipeline_id = storage.save_pipeline(response.dataset_id, "{}", [])
    storage.insert_run(response.dataset_id, pipeline_id, "run-1", "{}")
    storage.save_profile(response.dataset_id, "{}")
    assert storage.get_pipeline(response.dataset_id) is None
    assert storage.get_latest_run(response.dataset_id, pipeline_id) is None

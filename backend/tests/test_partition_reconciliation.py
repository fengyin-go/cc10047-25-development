"""分区重写核对、迟到更正、幂等发布和并发快照测试。"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '.')

from fastapi.testclient import TestClient

from app.main import app
from app.reconciliation import reconciliation_engine

client = TestClient(app)


def setup_function() -> None:
    reconciliation_engine.reset()


def test_m41_view_computes_moved_rows_and_pending_difference() -> None:
    response = client.get("/api/partition-rewrite-reconciliations/M41")
    assert response.status_code == 200
    view = response.json()
    assert view["task_code"] == "M41"
    assert view["source_partition"] == "p3"
    assert view["target_partition"] == "p4"
    summary = view["opened_view"]["summary"]
    assert summary["actual_moved_out_count"] == 5
    assert summary["actual_moved_in_count"] == 5
    assert summary["pending_difference_count"] == 0
    assert summary["duplicate_move_count"] == 0


def test_stale_scope_keeps_opened_k5_and_records_late_correction() -> None:
    late = client.post(
        "/api/partition-rewrite-reconciliations/M41/late-correction",
        json={"key": "k5"},
    ).json()
    assert late["evidence_record"]["before"]["value"] == "1005@opened-v1"
    assert late["evidence_record"]["after"]["value"] == "1005@late-corrected-v2"

    publication = client.post(
        "/api/partition-rewrite-reconciliations/M41/snapshots",
        json={"mode": "opened"},
        headers={"Idempotency-Key": "stale-test-key"},
    ).json()
    assert publication["scope_mode"] == "opened"
    assert publication["published_version"] == "RV-M41-v1"
    assert publication["p4_k5_readable_value"] == "1005@opened-v1"
    assert any(item["type"] == "late_correction_outside_published_scope"
               for item in publication["pending_records"])

    replay = client.post(
        "/api/partition-rewrite-reconciliations/M41/snapshots",
        json={"mode": "opened"},
        headers={"Idempotency-Key": "stale-test-key"},
    ).json()
    assert replay["snapshot_id"] == publication["snapshot_id"]
    assert replay["idempotent_replay"] is True

    checklist = client.get("/api/snapshot_mgr/publications").json()
    assert checklist["total"] == 1
    generic = client.get(f"/api/snapshot_mgr/{publication['snapshot_entry_id']}").json()
    assert generic["publication"]["snapshot_id"] == publication["snapshot_id"]
    assert generic["采用范围"] == "沿用打开时已核范围"


def test_refreshed_scope_adopts_corrected_k5_and_retains_evidence() -> None:
    client.post("/api/partition-rewrite-reconciliations/M41/late-correction", json={"key": "k5"})
    recheck = client.post("/api/partition-rewrite-reconciliations/M41/reverify").json()
    k5 = next(row for row in recheck["current_check"]["rows"] if row["key"] == "k5")
    assert k5["status"] == "late_correction_detected"

    publication = client.post(
        "/api/partition-rewrite-reconciliations/M41/snapshots",
        json={"mode": "refreshed"},
    ).json()
    assert publication["published_version"] == "RV-M41-v2"
    assert publication["p4_k5_readable_value"] == "1005@late-corrected-v2"
    assert publication["source_revision_at_open"] == 1
    assert publication["source_revision_at_publish"] == 2
    assert len(publication["evidence"]) >= 2
    assert any(item["type"] == "accepted_correction_pending_physical_rewrite"
               for item in publication["pending_records"])


def test_concurrent_publish_creates_one_snapshot_for_scope() -> None:
    scope = reconciliation_engine.open_scope(task_code="M41", new_session=True)
    scope_id = scope["id"]

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(
            lambda index: reconciliation_engine.publish_snapshot(
                scope_id, "opened", idempotency_key=f"key-{index}"
            ),
            range(32),
        ))

    assert len({item["publication_id"] for item in results}) == 1
    assert len({item["snapshot_id"] for item in results}) == 1
    assert sum(1 for item in results if item.get("concurrent_winner")) == 1

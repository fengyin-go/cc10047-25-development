"""分区重写核对视图和快照发布清单的 HTTP 接口。

主路径使用语义化复数资源；同时保留 partition_merge/snapshot_mgr 下的别名，
方便从既有模块进入，也兼容不同调用方对路径的命名习惯。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, Query

from app.reconciliation import DEFAULT_SCOPE_ID, reconciliation_engine

router = APIRouter(tags=["分区重写核对"])


def _payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    return payload or {}


# ----------------------------------------------------------------------
# 核对视图列表 / 打开范围
# ----------------------------------------------------------------------
@router.get("/api/partition-rewrite-reconciliations")
@router.get("/api/partition_rewrite_reconciliations")
@router.get("/api/partition-rewrite/views")
@router.get("/api/partition_rewrite_views")
@router.get("/api/reconciliation-views")
@router.get("/api/reconciliation_views")
@router.get("/api/partition_merge/reconciliations")
@router.get("/api/partition_merge/reconciliation")
@router.get("/api/partition_merge/views")
def list_reconciliation_views(
    source_partition: str | None = None,
    target_partition: str | None = None,
    task_code: str | None = None,
    source: str | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    return reconciliation_engine.list_views(
        source_partition=source_partition or source,
        target_partition=target_partition or target,
        task_code=task_code,
    )


@router.post("/api/partition-rewrite-reconciliations")
@router.post("/api/partition_rewrite_reconciliations")
@router.post("/api/partition-rewrite-reconciliations/open")
@router.post("/api/partition_rewrite_reconciliations/open")
@router.post("/api/partition-rewrite/open")
@router.post("/api/partition_rewrite/open")
@router.post("/api/reconciliation-views/open")
@router.post("/api/reconciliation_views/open")
@router.post("/api/partition_merge/reconciliations/open")
@router.post("/api/partition_merge/reconciliation/open")
def open_reconciliation_view(
    payload: dict[str, Any] | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    data = _payload(payload)
    task = data.get("task_code") or data.get("merge_id") or data.get("entry_id") or "M41"
    scope_key = data.get("scope_key") or data.get("scope_id")
    key = data.get("idempotency_key") or idempotency_key
    return reconciliation_engine.open_scope(
        task_code=task,
        scope_key=str(scope_key) if scope_key else None,
        new_session=bool(data.get("new_session", False)),
        idempotency_key=key,
    )


@router.get("/api/partition-rewrite-reconciliations/{scope_id}")
@router.get("/api/partition_rewrite_reconciliations/{scope_id}")
@router.get("/api/partition-rewrite/views/{scope_id}")
@router.get("/api/partition_rewrite_views/{scope_id}")
@router.get("/api/reconciliation-views/{scope_id}")
@router.get("/api/reconciliation_views/{scope_id}")
@router.get("/api/partition_merge/reconciliations/{scope_id}")
@router.get("/api/partition_merge/reconciliation/{scope_id}")
@router.get("/api/partition_merge/{entry_id}/reconciliation")
def get_reconciliation_view(scope_id: str | None = None, entry_id: str | None = None) -> dict[str, Any]:
    identifier = scope_id or entry_id or DEFAULT_SCOPE_ID
    view = reconciliation_engine.get_scope(identifier)
    if view is None:
        return {"ok": False, "message": f"找不到核对视图：{identifier}"}
    view["ok"] = True
    return view


# ----------------------------------------------------------------------
# 迟到更正 / 重新核验
# ----------------------------------------------------------------------
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/late-correction")
@router.post("/api/partition_rewrite_reconciliations/{scope_id}/late-correction")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/late_correction")
@router.post("/api/partition_rewrite_reconciliations/{scope_id}/late_correction")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/late-correct")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/late-update")
@router.post("/api/partition_rewrite_reconciliations/{scope_id}/late-update")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/late_update")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/corrections")
@router.post("/api/reconciliation-views/{scope_id}/late-correction")
@router.post("/api/reconciliation_views/{scope_id}/late_correction")
@router.post("/api/partition_merge/reconciliations/{scope_id}/late-correction")
@router.post("/api/partition_merge/{entry_id}/late-correction")
@router.post("/api/partition_merge/{entry_id}/late_correction")
def apply_late_correction(
    scope_id: str | None = None,
    entry_id: str | None = None,
    payload: dict[str, Any] | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    key: str | None = Query(default=None),
    row_key: str | None = Query(default=None),
    value: str | None = Query(default=None),
    corrected_value: str | None = Query(default=None),
    partition: str | None = Query(default=None),
) -> dict[str, Any]:
    data = _payload(payload)
    identifier = (
        scope_id
        or entry_id
        or data.get("scope_id")
        or data.get("scope_key")
        or data.get("scope")
        or DEFAULT_SCOPE_ID
    )
    selected_key = str(data.get("row_key") or data.get("key") or row_key or key or "k5")
    selected_value = (
        data.get("value", data.get("corrected_value", data.get("after_value")))
        or value
        or corrected_value
    )
    correction_id = data.get("correction_id") or idempotency_key
    return reconciliation_engine.apply_late_correction(
        identifier,
        row_key=selected_key,
        new_value=selected_value,
        correction_id=correction_id,
        source_partition=data.get("source_partition") or data.get("partition") or partition,
    )


@router.post("/api/partition-rewrite-reconciliations/{scope_id}/reverify")
@router.post("/api/partition_rewrite_reconciliations/{scope_id}/reverify")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/re_verify")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/refresh")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/recheck")
@router.post("/api/reconciliation-views/{scope_id}/reverify")
@router.post("/api/reconciliation_views/{scope_id}/reverify")
@router.post("/api/partition_merge/reconciliations/{scope_id}/reverify")
@router.post("/api/partition_merge/{entry_id}/reverify")
def reverify_view(scope_id: str | None = None, entry_id: str | None = None) -> dict[str, Any]:
    return reconciliation_engine.reverify(scope_id or entry_id or DEFAULT_SCOPE_ID)


# ----------------------------------------------------------------------
# 从核对范围登记/发布快照
# ----------------------------------------------------------------------
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/snapshots")
@router.post("/api/partition_rewrite_reconciliations/{scope_id}/snapshots")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/publish")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/publish-snapshot")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/publish_snapshot")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/register-snapshot")
@router.post("/api/partition-rewrite-reconciliations/{scope_id}/register_snapshot")
@router.post("/api/reconciliation-views/{scope_id}/snapshots")
@router.post("/api/reconciliation_views/{scope_id}/snapshots")
@router.post("/api/snapshot_mgr/publications")
@router.post("/api/snapshot_mgr/reconciliation-publications")
@router.post("/api/snapshot_mgr/reconciliation_publications")
@router.post("/api/snapshot_mgr/register-reconciliation-snapshot")
@router.post("/api/partition_merge/reconciliations/{scope_id}/snapshots")
@router.post("/api/partition_merge/{entry_id}/snapshots")
@router.post("/api/partition_merge/{entry_id}/register-snapshot")
@router.post("/api/partition_merge/{entry_id}/register_snapshot")
def publish_snapshot_from_view(
    scope_id: str | None = None,
    entry_id: str | None = None,
    payload: dict[str, Any] | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    mode: str | None = Query(default=None),
    scope_mode: str | None = Query(default=None),
) -> dict[str, Any]:
    data = _payload(payload)
    identifier = (
        scope_id
        or entry_id
        or data.get("scope_id")
        or data.get("scope_key")
        or data.get("scope")
        or data.get("id")
        or DEFAULT_SCOPE_ID
    )
    selected_mode = str(
        data.get("mode")
        or data.get("scope_mode")
        or data.get("adoption_mode")
        or mode
        or scope_mode
        or "opened"
    )
    key = data.get("idempotency_key") or idempotency_key
    return reconciliation_engine.publish_snapshot(
        identifier,
        mode=selected_mode,
        idempotency_key=key,
        snapshot_label=data.get("snapshot_label") or data.get("remark"),
    )


# ----------------------------------------------------------------------
# 快照发布清单和详情
# ----------------------------------------------------------------------
@router.get("/api/partition-rewrite-snapshots")
@router.get("/api/partition_rewrite_snapshots")
@router.get("/api/partition-rewrite/publications")
@router.get("/api/partition_rewrite/publications")
@router.get("/api/snapshot-publications")
@router.get("/api/snapshot_publications")
@router.get("/api/snapshot_mgr/publications")
@router.get("/api/snapshot_mgr/publish-list")
@router.get("/api/snapshot_mgr/publish_list")
@router.get("/api/snapshot_mgr/reconciliation-publications")
@router.get("/api/snapshot_mgr/reconciliation_publications")
def list_snapshot_publications() -> dict[str, Any]:
    return reconciliation_engine.list_publications()


@router.get("/api/partition-rewrite-snapshots/{publication_id}")
@router.get("/api/partition_rewrite_snapshots/{publication_id}")
@router.get("/api/snapshot-publications/{publication_id}")
@router.get("/api/snapshot_publications/{publication_id}")
@router.get("/api/snapshot_mgr/publications/{publication_id}")
def get_snapshot_publication(publication_id: str) -> dict[str, Any]:
    publication = reconciliation_engine.get_publication(publication_id)
    if publication is None:
        return {"ok": False, "message": f"找不到快照发布记录：{publication_id}"}
    publication["ok"] = True
    return publication


@router.post("/api/testing/reset-partition-reconciliation")
def reset_partition_reconciliation() -> dict[str, Any]:
    """测试/演示辅助：重置 M41 内存核对场景。"""
    reconciliation_engine.reset()
    return {"ok": True, "message": "分区重写核对场景已重置"}

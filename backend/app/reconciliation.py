"""分区重写核对与快照发布的内存领域引擎。

该模块只依赖标准库和全局内存仓库：
- 打开视图时固化已核版本和来源证据；
- 迟到更正保留更正前后证据；
- 发布按核对范围幂等，并用进程内锁保证并发下只有一份快照；
- 移出键按业务键去重，迟到更正不会第二次计为“移出”。
"""
from __future__ import annotations

import hashlib
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.store import store

K5_OPENED_VALUE = "1005@opened-v1"
K5_LATE_VALUE = "1005@late-corrected-v2"
DEFAULT_SCOPE_ID = "RCV-M41-P3-P4"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _checksum(row_key: str, value: Any) -> str:
    digest = hashlib.sha256(f"{row_key}={value}".encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def _data_row(row_key: str, value: Any, revision: int = 1) -> dict[str, Any]:
    return {
        "key": row_key,
        "value": value,
        "revision": revision,
        "checksum": _checksum(row_key, value),
        "updated_at": _now(),
    }


class PartitionReconciliationEngine:
    """线程安全的核对范围、证据和发布清单存储。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        """恢复 M41 初始场景。主要给自测和演示重置使用。"""
        with self._lock:
            self.scopes: dict[str, dict[str, Any]] = {}
            self.publications: dict[str, dict[str, Any]] = {}
            self.idempotency_index: dict[str, str] = {}
            self.scope_aliases: dict[str, str] = {}
            self.task_state: dict[str, dict[str, Any]] = {}
            self._publication_seq = 0
            self._scope_seq = 0
            snapshot_rows = store.rows("snapshot_mgr")
            snapshot_rows[:] = [row for row in snapshot_rows if not row.get("publication_id")]
            self._seed_m41()
            self.open_scope(task_code="M41", scope_key=DEFAULT_SCOPE_ID)

    # ------------------------------------------------------------------
    # 种子数据
    # ------------------------------------------------------------------
    def _seed_m41(self) -> None:
        source_rows = {
            "k1": _data_row("k1", "1001"),
            "k2": _data_row("k2", "1002"),
            "k3": _data_row("k3", "1003"),
            "k4": _data_row("k4", "1004"),
            "k5": _data_row("k5", K5_OPENED_VALUE),
        }
        target_rows = {
            "k1": _data_row("k1", "1001"),
            "k2": _data_row("k2", "1002"),
            "k3": _data_row("k3", "1003"),
            "k4": _data_row("k4", "1004"),
            "k5": _data_row("k5", K5_OPENED_VALUE),
        }
        move_keys = ["k1", "k2", "k3", "k4", "k5"]
        self.task_state["M41"] = {
            "task_code": "M41",
            "merge_entry_id": 41,
            "table_name": "lakehouse.order_event",
            "source_partition": "p3",
            "target_partition": "p4",
            "source_revision": 1,
            "target_revision": 1,
            "source_rows": source_rows,
            "target_rows": target_rows,
            "move_ledger": [
                {
                    "move_event_id": f"MOVE-M41-P3-P4-{key}",
                    "task_code": "M41",
                    "row_key": key,
                    "direction": "moved_out_and_in",
                    "count": 1,
                    "counted_once": True,
                }
                for key in move_keys
            ],
            "moved_out_keys": move_keys,
            "evidence": [
                {
                    "evidence_id": "EV-M41-K5-R1",
                    "task_code": "M41",
                    "partition": "p3",
                    "row_key": "k5",
                    "revision": 1,
                    "kind": "opened_baseline",
                    "received_at": _now(),
                    "before": None,
                    "after": deepcopy(source_rows["k5"]),
                    "retained": True,
                }
            ],
            "active_scope_id": None,
        }

    # ------------------------------------------------------------------
    # 范围解析和视图版本
    # ------------------------------------------------------------------
    def _resolve_scope_id(self, identifier: str | int | None) -> str | None:
        if identifier is None:
            return self.task_state["M41"]["active_scope_id"]
        raw = str(identifier).strip()
        if raw in self.scopes:
            return raw
        if raw in self.scope_aliases:
            return self.scope_aliases[raw]
        if raw in self.task_state:
            return self.task_state[raw].get("active_scope_id")
        # 允许传数字资源 id=41。
        for code, state in self.task_state.items():
            if str(state.get("merge_entry_id")) == raw:
                return state.get("active_scope_id")
        return None

    def _scope_or_error(self, identifier: str | int | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        scope_id = self._resolve_scope_id(identifier)
        if not scope_id or scope_id not in self.scopes:
            return None, {"ok": False, "message": f"找不到分区重写核对范围：{identifier}"}
        return self.scopes[scope_id], None

    def open_scope(
        self,
        task_code: str | int | None = "M41",
        scope_key: str | None = None,
        new_session: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if idempotency_key and idempotency_key in self.idempotency_index:
                pub_id = self.idempotency_index[idempotency_key]
                # 打开范围的幂等键若已用于发布，仍返回对应范围。
                if pub_id in self.publications:
                    scope_id = self.publications[pub_id]["scope_id"]
                    return self.get_scope(scope_id)  # type: ignore[return-value]
            code = str(task_code or "M41")
            # 兼容直接传资源数字 id。
            if code == "41":
                code = "M41"
            state = self.task_state.get(code)
            if state is None:
                return {"ok": False, "message": f"未知分区重写任务：{code}"}

            if scope_key and scope_key in self.scopes:
                return self.get_scope(scope_key)  # type: ignore[return-value]
            if not new_session and not scope_key and state.get("active_scope_id"):
                return self.get_scope(state["active_scope_id"])  # type: ignore[return-value]

            self._scope_seq += 1
            scope_id = scope_key or f"RCV-{code}-{self._scope_seq:04d}-{uuid.uuid4().hex[:8]}"
            version = self._build_version(state, kind="opened", version_number=1)
            scope: dict[str, Any] = {
                "ok": True,
                "id": scope_id,
                "scope_id": scope_id,
                "scope_key": scope_id,
                "task_code": code,
                "merge_entry_id": state["merge_entry_id"],
                "table_name": state["table_name"],
                "source_partition": state["source_partition"],
                "target_partition": state["target_partition"],
                "title": f"{code} {state['source_partition']}→{state['target_partition']} 分区重写核对",
                "status": "opened",
                "opened_at": _now(),
                "opened_version_id": version["version_id"],
                "current_version_id": version["version_id"],
                "adopted_version_id": None,
                "publish_mode": None,
                "source_revision_at_open": state["source_revision"],
                "source_revision_current": state["source_revision"],
                "versions": [version],
                "rechecks": [],
                "events": [],
                "publication_id": None,
                "snapshot_id": None,
                "client_idempotency_key": idempotency_key,
                "scope_statement": (
                    f"打开视图时已核范围：{state['table_name']} {code} "
                    f"{state['source_partition']} → {state['target_partition']}，"
                    f"来源版本 r{state['source_revision']}，核对版本 {version['version_id']}"
                ),
            }
            self.scopes[scope_id] = scope
            self.scope_aliases[scope_id] = scope_id
            self.scope_aliases[code] = scope_id
            self.scope_aliases[f"{code}:{state['source_partition']}:{state['target_partition']}"] = scope_id
            state["active_scope_id"] = scope_id
            if idempotency_key:
                # 打开阶段先记住键；发布时同一键仍只映射到一份发布。
                self.idempotency_index[f"open:{idempotency_key}"] = scope_id
            return self.get_scope(scope_id)  # type: ignore[return-value]

    def _build_version(
        self,
        state: dict[str, Any],
        *,
        kind: str,
        version_number: int,
        adopt_current_source: bool = False,
        base_version: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造某一核对版本的行级数据和汇总。

        kind=opened 时使用 base_version 中打开时固化的来源值；
        kind=refreshed 时读取当前来源，并可采纳更正作为 p4 可读值。
        """
        rows: list[dict[str, Any]] = []
        moved_out = 0
        moved_in = 0
        matched = 0
        pending_diff = 0
        drift_count = 0

        opened_source_values: dict[str, Any] = {}
        if base_version is not None:
            opened_source_values = {
                row["key"]: row.get("source_value") for row in base_version.get("rows", [])
            }

        for key in state["moved_out_keys"]:
            source_row = state["source_rows"][key]
            target_row = state["target_rows"].get(key)
            current_source_value = source_row["value"]
            # 打开版本必须读打开时快照，不能被后续迟到更正改写。
            source_value = (
                opened_source_values.get(key, current_source_value)
                if kind == "opened"
                else current_source_value
            )
            stored_target_value = target_row["value"] if target_row else None
            readable_value = stored_target_value
            status = "matched"
            label = "一致"
            pending = False
            correction_adopted = False

            source_changed_after_open = (
                kind != "opened"
                and base_version is not None
                and opened_source_values.get(key) != current_source_value
            )
            current_matches_target = current_source_value == stored_target_value

            if target_row is None:
                status = "missing_in_target"
                label = "目标缺失"
                pending = True
            elif kind == "opened":
                if source_value == stored_target_value:
                    status = "matched_opened_scope"
                    label = "一致（打开时已核范围）"
                    matched += 1
                else:
                    status = "checksum_mismatch"
                    label = "待核差异：源/目标值不一致"
                    pending = True
            elif adopt_current_source and source_changed_after_open:
                # 登记前重新核验并采纳更正：读模型采用更正后的来源值，
                # 但物理 p4 的追加重写仍是未结事项。
                readable_value = current_source_value
                status = "correction_adopted_pending_rewrite"
                label = "已采纳迟到更正，待物理重写 p4"
                correction_adopted = True
                drift_count += 0 if current_matches_target else 1
            elif not current_matches_target:
                status = "late_correction_detected" if source_changed_after_open else "checksum_mismatch"
                label = "待核差异：当前来源与 p4 不一致"
                pending = True
                drift_count += 1
            else:
                status = "matched_current_scope"
                label = "一致（重新核验）"
                matched += 1

            if pending:
                pending_diff += 1
            moved_out += 1
            if target_row is not None:
                moved_in += 1

            rows.append({
                "key": key,
                "row_key": key,
                "source_partition": state["source_partition"],
                "target_partition": state["target_partition"],
                "source_value": source_value,
                "current_source_value": current_source_value,
                "source_revision": source_row.get("revision", 1),
                "stored_p4_value": stored_target_value,
                "stored_target_value": stored_target_value,
                "p4_readable_value": readable_value,
                "readable_value": readable_value,
                "move_status": "实际移出；实际移入" if target_row else "实际移出；目标缺失",
                "status": status,
                "difference_status": status,
                "status_label": label,
                "pending_difference": pending,
                "correction_adopted": correction_adopted,
                "source_changed_after_open": source_changed_after_open,
                "move_event_id": f"MOVE-{state['task_code']}-P3-P4-{key}",
                "move_count": 1,
                "counted_once": True,
            })

        # 目标端额外记录。
        for key, target_row in state["target_rows"].items():
            if key in state["moved_out_keys"]:
                continue
            pending_diff += 1
            rows.append({
                "key": key,
                "row_key": key,
                "source_partition": state["source_partition"],
                "target_partition": state["target_partition"],
                "source_value": None,
                "current_source_value": None,
                "source_revision": None,
                "stored_p4_value": target_row["value"],
                "stored_target_value": target_row["value"],
                "p4_readable_value": target_row["value"],
                "readable_value": target_row["value"],
                "move_status": "目标额外记录",
                "status": "extra_in_target",
                "difference_status": "extra_in_target",
                "status_label": "待核差异：目标额外记录",
                "pending_difference": True,
                "correction_adopted": False,
                "source_changed_after_open": False,
                "move_event_id": None,
                "move_count": 0,
                "counted_once": True,
            })

        version_id = f"RV-{state['task_code']}-v{version_number}"
        return {
            "version_id": version_id,
            "version": version_id,
            "version_number": version_number,
            "kind": kind,
            "adopt_current_source": adopt_current_source,
            "created_at": _now(),
            "source_revision": state["source_revision"],
            "target_revision": state["target_revision"],
            "rows": rows,
            "summary": {
                "actual_moved_out_count": moved_out,
                "actual_moved_in_count": moved_in,
                "matched_count": matched,
                "pending_difference_count": pending_diff,
                "current_source_drift_count": drift_count,
                "distinct_moved_out_keys": len(set(state["moved_out_keys"])),
                "duplicate_move_count": 0,
            },
            "moved_out_rows": moved_out,
            "moved_in_rows": moved_in,
            "pending_differences": pending_diff,
        }

    def get_scope(self, identifier: str | int | None) -> dict[str, Any] | None:
        with self._lock:
            scope_id = self._resolve_scope_id(identifier)
            if not scope_id:
                return None
            scope = self.scopes[scope_id]
            result = deepcopy(scope)
            state = self.task_state[scope["task_code"]]
            result["source_evidence"] = deepcopy(state["evidence"])
            result["evidence"] = deepcopy(state["evidence"])
            result["source_revision_current"] = state["source_revision"]
            result["current_source_revision"] = state["source_revision"]
            # 始终附带当前计算视图，方便刷新页面后直接渲染。
            opened_version = next(
                (item for item in scope["versions"] if item["version_id"] == scope["opened_version_id"]),
                scope["versions"][0],
            )
            result["opened_view"] = opened_version
            result["current_check"] = scope.get("latest_recheck") or self._build_version(
                state,
                kind="recheck_preview",
                version_number=2,
                adopt_current_source=False,
                base_version=opened_version,
            )
            adopted_id = scope.get("adopted_version_id")
            if adopted_id:
                result["adopted_view"] = next(
                    (item for item in scope["versions"] if item["version_id"] == adopted_id),
                    None,
                )
            result["pending_records"] = self._pending_records(scope, state)
            result["pending_record_count"] = len(result["pending_records"])
            # 顶层保留一份打开时汇总，方便调用方直接断言 actual_moved_* 字段。
            result["summary"] = opened_version["summary"]
            result.update(opened_version["summary"])
            return result

    def list_views(
        self,
        *,
        source_partition: str | None = None,
        target_partition: str | None = None,
        task_code: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            items = []
            # 新打开的会话排在前面；固定 M41 范围在首次进入时仍是唯一一项。
            for scope in reversed(list(self.scopes.values())):
                if source_partition and source_partition.strip().casefold() not in str(
                    scope.get("source_partition", "")
                ).casefold():
                    continue
                if target_partition and target_partition.strip().casefold() not in str(
                    scope.get("target_partition", "")
                ).casefold():
                    continue
                if task_code and task_code.strip().casefold() not in str(
                    scope.get("task_code", "")
                ).casefold():
                    continue
                detailed = self.get_scope(scope["id"])
                if detailed:
                    items.append({
                        key: detailed.get(key)
                        for key in [
                            "id", "scope_id", "task_code", "title", "status", "table_name",
                            "source_partition", "target_partition", "opened_at",
                            "opened_version_id", "current_version_id", "adopted_version_id",
                            "publish_mode", "publication_id", "snapshot_id",
                            "scope_statement", "source_revision_at_open",
                            "source_revision_current", "pending_record_count",
                        ]
                    } | {"summary": detailed["opened_view"]["summary"]})
            return {"items": items, "total": len(items)}

    # ------------------------------------------------------------------
    # 迟到更正和重新核验
    # ------------------------------------------------------------------
    def apply_late_correction(
        self,
        identifier: str | int | None = DEFAULT_SCOPE_ID,
        *,
        row_key: str = "k5",
        new_value: Any | None = None,
        correction_id: str | None = None,
        source_partition: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            scope, error = self._scope_or_error(identifier)
            if error:
                return error
            assert scope is not None
            state = self.task_state[scope["task_code"]]
            partition = source_partition or state["source_partition"]
            if partition != state["source_partition"]:
                return {"ok": False, "message": f"迟到更正必须来自旧源分区 {state['source_partition']}"}
            if row_key not in state["source_rows"]:
                return {"ok": False, "message": f"来源 {partition} 中不存在 row key {row_key}"}

            # 重试同一个 correction_id 时不重复制造版本/证据。
            if correction_id:
                for evidence in state["evidence"]:
                    if evidence.get("correction_id") == correction_id:
                        detailed = self.get_scope(scope["id"])
                        assert detailed is not None
                        detailed.update({
                            "ok": True,
                            "idempotent_replay": True,
                            "message": "迟到更正请求已处理，返回保留的更正前后证据",
                            "evidence_record": evidence,
                        })
                        return detailed

            before_row = deepcopy(state["source_rows"][row_key])
            if new_value is None or str(new_value) == "":
                # 默认更正只对 k5 使用稳定可辨识的值；其他键追加 late 标记。
                new_value = K5_LATE_VALUE if row_key == "k5" else f"{before_row['value']}@late-corrected"
            if before_row["value"] == new_value:
                evidence_record = state["evidence"][-1]
            else:
                state["source_revision"] += 1
                after_row = _data_row(row_key, new_value, state["source_revision"])
                state["source_rows"][row_key] = after_row
                evidence_record = {
                    "evidence_id": f"EV-{scope['task_code']}-{row_key.upper()}-R{state['source_revision']}",
                    "task_code": scope["task_code"],
                    "correction_id": correction_id or f"LATE-{uuid.uuid4().hex[:8]}",
                    "partition": partition,
                    "row_key": row_key,
                    "key": row_key,
                    "revision": state["source_revision"],
                    "kind": "late_correction",
                    "received_at": _now(),
                    "before": {
                        "value": before_row["value"],
                        "checksum": before_row["checksum"],
                        "revision": before_row.get("revision", 1),
                    },
                    "after": {
                        "value": after_row["value"],
                        "checksum": after_row["checksum"],
                        "revision": after_row["revision"],
                    },
                    "retained_before_and_after": True,
                    "survives_disconnect": True,
                }
                state["evidence"].append(evidence_record)
                scope["source_revision_current"] = state["source_revision"]
                scope["events"].append({
                    "at": _now(),
                    "type": "late_correction",
                    "row_key": row_key,
                    "evidence_id": evidence_record["evidence_id"],
                })

            detailed = self.get_scope(scope["id"])
            assert detailed is not None
            detailed.update({
                "ok": True,
                "message": f"旧 {partition} 来源的 {row_key} 迟到更正已留证",
                "evidence_record": evidence_record,
            })
            return detailed

    def reverify(self, identifier: str | int | None) -> dict[str, Any]:
        with self._lock:
            scope, error = self._scope_or_error(identifier)
            if error:
                return error
            assert scope is not None
            state = self.task_state[scope["task_code"]]
            opened_version = next(
                item for item in scope["versions"]
                if item["version_id"] == scope["opened_version_id"]
            )
            check = self._build_version(
                state,
                kind="recheck_preview",
                version_number=2,
                adopt_current_source=False,
                base_version=opened_version,
            )
            check["checked_at"] = _now()
            scope["latest_recheck"] = check
            scope["rechecks"].append(deepcopy(check))
            scope["current_version_id"] = check["version_id"]
            detailed = self.get_scope(scope["id"])
            assert detailed is not None
            detailed.update({"ok": True, "message": "已重新核验当前来源，未采纳前不改变发布范围"})
            return detailed

    # ------------------------------------------------------------------
    # 待处理记录和发布
    # ------------------------------------------------------------------
    def _pending_records(self, scope: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
        adopted_id = scope.get("adopted_version_id") or scope["opened_version_id"]
        version = next((item for item in scope["versions"] if item["version_id"] == adopted_id), None)
        if version is None:
            return []
        records: list[dict[str, Any]] = []
        for row in version["rows"]:
            if row.get("pending_difference"):
                records.append({
                    "id": f"PEND-{scope['task_code']}-{row['key'].upper()}-DIFF",
                    "type": "pending_difference",
                    "row_key": row["key"],
                    "partition": scope["target_partition"],
                    "status": "待核差异",
                    "message": row["status_label"],
                    "source_value": row.get("source_value"),
                    "p4_readable_value": row.get("p4_readable_value"),
                    "opened": True,
                })
            elif row.get("correction_adopted"):
                records.append({
                    "id": f"PEND-{scope['task_code']}-{row['key'].upper()}-REWRITE",
                    "type": "accepted_correction_pending_physical_rewrite",
                    "row_key": row["key"],
                    "partition": scope["target_partition"],
                    "status": "待处理：更正待物理重写",
                    "message": "更正核对版本已发布；p4 物理文件仍需追加一次重写并复核",
                    "corrected_readable_value": row.get("p4_readable_value"),
                    "stored_p4_value": row.get("stored_p4_value"),
                    "evidence_id": f"EV-{scope['task_code']}-{row['key'].upper()}-R{state['source_revision']}",
                })

        opened_version = next(
            item for item in scope["versions"]
            if item["version_id"] == scope["opened_version_id"]
        )
        opened_values = {row["key"]: row.get("source_value") for row in opened_version["rows"]}
        changed_keys = [
            key for key, source_row in state["source_rows"].items()
            if opened_values.get(key) != source_row["value"]
        ]

        # 沿用原范围发布后，未纳入的迟到更正继续挂账。
        if scope.get("publish_mode") == "opened":
            for key in changed_keys:
                source_row = state["source_rows"][key]
                records.append({
                    "id": f"PEND-{scope['task_code']}-{key.upper()}-LATE",
                    "type": "late_correction_outside_published_scope",
                    "row_key": key,
                    "partition": state["source_partition"],
                    "status": "待处理：迟到更正未纳入发布范围",
                    "message": (
                        f"快照沿用 {scope['opened_version_id']}；"
                        f"{state['source_partition']} 的迟到更正需另立核对范围处理"
                    ),
                    "published_p4_readable_value": opened_values.get(key),
                    "current_source_value": source_row["value"],
                    "evidence_id": f"EV-{scope['task_code']}-{key.upper()}-R{state['source_revision']}",
                })
        elif not scope.get("publish_mode"):
            # 登记前：当前来源和打开时范围不同，先作为待核/待选择记录展示。
            for key in changed_keys:
                source_row = state["source_rows"][key]
                records.append({
                    "id": f"PEND-{scope['task_code']}-{key.upper()}-CURRENT-DRIFT",
                    "type": "late_correction_detected_pending_scope_choice",
                    "row_key": key,
                    "partition": state["source_partition"],
                    "status": "待核差异：迟到更正等待选择发布范围",
                    "message": "可沿用打开时范围，或重新核验并采纳更正后的 v2",
                    "opened_p4_readable_value": opened_values.get(key),
                    "current_source_value": source_row["value"],
                    "evidence_id": f"EV-{scope['task_code']}-{key.upper()}-R{state['source_revision']}",
                })
        return records

    def publish_snapshot(
        self,
        identifier: str | int | None,
        mode: str = "opened",
        idempotency_key: str | None = None,
        snapshot_label: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if idempotency_key and idempotency_key in self.idempotency_index:
                existing_id = self.idempotency_index[idempotency_key]
                if existing_id in self.publications:
                    publication = deepcopy(self.publications[existing_id])
                    publication.update({
                        "ok": True,
                        "idempotent_replay": True,
                        "concurrent_winner": False,
                        "message": "请求重试已返回同一快照，未重复发布",
                    })
                    return publication

            scope, error = self._scope_or_error(identifier)
            if error:
                return error
            assert scope is not None

            # 同一核对范围只生效一次：并发请求在锁后都会走到已发布分支。
            if scope.get("publication_id"):
                publication = deepcopy(self.publications[scope["publication_id"]])
                if idempotency_key:
                    self.idempotency_index[idempotency_key] = publication["id"]
                publication.update({
                    "ok": True,
                    "idempotent_replay": True,
                    "already_published_for_scope": True,
                    "concurrent_winner": False,
                    "message": "同一核对范围已发布，只保留这一份快照",
                })
                return publication

            normalized_mode = self._normalize_mode(mode)
            state = self.task_state[scope["task_code"]]
            opened_version = next(
                item for item in scope["versions"]
                if item["version_id"] == scope["opened_version_id"]
            )

            if normalized_mode == "refreshed":
                adopted_version = self._build_version(
                    state,
                    kind="refreshed_adopted",
                    version_number=2,
                    adopt_current_source=True,
                    base_version=opened_version,
                )
                # 若没有任何迟到更正，v2 仍可作为登记前重新核验版本。
                scope["versions"].append(adopted_version)
                scope["adopted_version_id"] = adopted_version["version_id"]
                scope["current_version_id"] = adopted_version["version_id"]
                scope["publish_mode"] = "refreshed"
                scope["scope_adoption_statement"] = (
                    f"登记前已重新核验当前来源 r{state['source_revision']}，"
                    f"采用更正后的核对版本 {adopted_version['version_id']}"
                )
            else:
                adopted_version = opened_version
                scope["adopted_version_id"] = opened_version["version_id"]
                scope["current_version_id"] = opened_version["version_id"]
                scope["publish_mode"] = "opened"
                scope["scope_adoption_statement"] = (
                    f"沿用打开视图时的已核范围 {opened_version['version_id']}；"
                    "登记前的新来源更正不回溯进本次快照"
                )

            self._publication_seq += 1
            seq = self._publication_seq
            publication_id = f"PUB-{scope['task_code']}-{seq:04d}"
            snapshot_id = f"SNAP-{scope['task_code']}-{seq:04d}"
            release_version = f"REL-{scope['task_code']}-v{seq}"
            pending_records = self._pending_records(scope, state)
            k5_row = next((row for row in adopted_version["rows"] if row["key"] == "k5"), None)
            evidence = deepcopy(state["evidence"])
            conclusion = {
                "actual_moved_out": adopted_version["summary"]["actual_moved_out_count"],
                "actual_moved_in": adopted_version["summary"]["actual_moved_in_count"],
                "pending_differences": adopted_version["summary"]["pending_difference_count"],
                "matched": adopted_version["summary"]["matched_count"],
                "duplicate_moved_out": adopted_version["summary"]["duplicate_move_count"],
                "one_move_per_row": True,
            }
            publication: dict[str, Any] = {
                "ok": True,
                "id": publication_id,
                "publication_id": publication_id,
                "snapshot_id": snapshot_id,
                "release_version": release_version,
                "published_version": adopted_version["version_id"],
                "reconciliation_version": adopted_version["version_id"],
                "scope_id": scope["id"],
                "scope_key": scope["id"],
                "task_code": scope["task_code"],
                "merge_entry_id": scope["merge_entry_id"],
                "table_name": scope["table_name"],
                "source_partition": scope["source_partition"],
                "target_partition": scope["target_partition"],
                "mode": normalized_mode,
                "scope_mode": normalized_mode,
                "adoption_mode": normalized_mode,
                "scope_statement": scope["scope_statement"],
                "adoption_statement": scope["scope_adoption_statement"],
                "published_scope_description": (
                    scope["scope_statement"] + "；本次发布采用：" + scope["scope_adoption_statement"]
                ),
                "opened_version_id": opened_version["version_id"],
                "adopted_version_id": adopted_version["version_id"],
                "source_revision_at_open": scope["source_revision_at_open"],
                "source_revision_at_publish": state["source_revision"],
                "k5": k5_row,
                "p4_k5_readable_value": (k5_row or {}).get("p4_readable_value"),
                "conclusion": conclusion,
                "summary": adopted_version["summary"],
                "actual_moved_out_count": conclusion["actual_moved_out"],
                "actual_moved_in_count": conclusion["actual_moved_in"],
                "moved_out_count": conclusion["actual_moved_out"],
                "moved_in_count": conclusion["actual_moved_in"],
                "pending_difference_count": conclusion["pending_differences"],
                "pending_diff_count": conclusion["pending_differences"],
                "pending_records": pending_records,
                "pending_record_count": len(pending_records),
                "evidence": evidence,
                "source_evidence": evidence,
                "created_at": _now(),
                "snapshot_label": snapshot_label or "分区重写核对发布快照",
                "idempotency_key": idempotency_key,
                "concurrent_winner": True,
            }

            # 同步一份到通用快照管理资源，使现有列表/详情接口也能读到。
            rows = store.rows("snapshot_mgr")
            snapshot_row_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
            snapshot_row = {
                "id": snapshot_row_id,
                "status": "可用",
                "pending": False,
                "abnormal": False,
                "快照标识": snapshot_id,
                "目标湖表": scope["table_name"],
                "快照时间": publication["created_at"],
                "数据行数": conclusion["actual_moved_in"],
                "存储大小": "512 MB",
                "过期时间": "保留 30 天",
                "快照标签": "partition-rewrite-release",
                "保留状态": "已发布",
                "publication_id": publication_id,
                "release_version": release_version,
                "reconciliation_scope_id": scope["id"],
                "reconciliation_version": adopted_version["version_id"],
                "采用范围": "沿用打开时已核范围" if normalized_mode == "opened" else "刷新后更正版本",
                "p4-k5": publication["p4_k5_readable_value"],
                "pending_record_count": len(pending_records),
            }
            rows.append(snapshot_row)
            publication["snapshot_row_id"] = snapshot_row_id
            publication["snapshot_entry_id"] = snapshot_row_id

            self.publications[publication_id] = publication
            scope["publication_id"] = publication_id
            scope["snapshot_id"] = snapshot_id
            scope["snapshot_row_id"] = snapshot_row_id
            scope["status"] = "published"
            if idempotency_key:
                self.idempotency_index[idempotency_key] = publication_id
            return deepcopy(publication)

    @staticmethod
    def _normalize_mode(mode: str | None) -> str:
        text = str(mode or "opened").strip().casefold()
        refreshed_tokens = {
            "refreshed", "refresh", "current", "reverify", "recheck", "corrected",
            "刷新", "重新核验", "刷新后", "刷新后版本", "更正版", "采用更正",
            "登记前重新核验", "刷新并采用更正版本",
        }
        if text in refreshed_tokens or "刷新" in text or "重新核验" in text or "更正" in text:
            return "refreshed"
        return "opened"

    def list_publications(self) -> dict[str, Any]:
        with self._lock:
            items = sorted(
                (deepcopy(item) for item in self.publications.values()),
                key=lambda item: item["created_at"],
                reverse=True,
            )
            return {"items": items, "total": len(items)}

    def get_publication(self, publication_id: str) -> dict[str, Any] | None:
        with self._lock:
            pub = self.publications.get(publication_id)
            if pub:
                return deepcopy(pub)
            # 允许用 SNAP-/REL-/scope id 查询。
            for item in self.publications.values():
                if publication_id in {item["snapshot_id"], item["release_version"], item["scope_id"]}:
                    return deepcopy(item)
            return None


reconciliation_engine = PartitionReconciliationEngine()

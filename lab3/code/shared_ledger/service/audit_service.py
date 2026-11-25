"""审核服务。

对应实验二组件图中的记录与审核模块 `AuditService`。

管理员对记录的三种处理：通过、驳回、作废，全部要求填写原因的操作
（驳回、作废）缺一不可（REQ-010、REQ-012）。

本模块还承担冲正生效的动作：冲正记录审核通过时，原记录同步由已通过
变为已冲正，并互相登记关联标识（REQ-013）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List

from ..domain.entities import Record, RecordTrace
from ..domain.enums import LogActionType, RecordStatus
from ..domain.errors import BusinessRuleError, StateConflictError, ValidationError
from ..domain.support_ids import new_uuid
from ..persistence.repositories import RepositoryRegistry
from ..support.optimistic_lock import OptimisticLock
from ..support.state_guard import StateGuard
from .base import BaseService, with_denial_log
from .reversal import apply_reversal_effect


class AuditService(BaseService):
    """审核服务。"""

    def __init__(
        self, repos: RepositoryRegistry, access: Any, logs: Any = None
    ) -> None:
        """初始化服务。

        :param repos: 仓储集合。
        :param access: 权限守卫。
        :param logs: 日志服务。
        """
        super().__init__(repos, access, logs)

    @with_denial_log
    def list_pending(self, actor_user_id: str, ledger_id: str) -> List[Record]:
        """列出账本内全部待审核记录。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :return: 待审核记录列表，按提交时间升序。
        """
        self.access.require_admin(ledger_id, actor_user_id)
        return self.repos.records.list_by_status(ledger_id, RecordStatus.PENDING)

    @with_denial_log
    def approve(self, actor_user_id: str, ledger_id: str, record_id: str) -> Record:
        """审核通过一条待审核记录。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :param record_id: 记录标识。
        :return: 更新后的记录。
        :raises StateConflictError: 记录状态已变更。
        """
        member = self.access.require_admin(ledger_id, actor_user_id)
        record = self._require_pending(ledger_id, record_id)

        StateGuard.assert_record_transition(
            record.status, RecordStatus.APPROVED, subject="记录"
        )

        now = datetime.now()
        previous = record.status
        record.status = RecordStatus.APPROVED
        record.reviewed_at = now
        record.reviewer_id = member.member_id
        record.version = OptimisticLock.next_version(record.version)

        with self.repos.database.transaction():
            self.repos.records.save(record)
            self._write_trace(
                record, LogActionType.RECORD_APPROVE, member.member_id, "", previous
            )
            self.logs.append_params(
                ledger_id,
                member.member_id,
                LogActionType.RECORD_APPROVE,
                "收支记录",
                record.record_id,
                {
                    "金额": str(record.amount),
                    "分类": record.category_name,
                    "记账日期": record.record_date.isoformat(),
                    "结论": "已通过，已计入统计",
                },
            )
            self._apply_reversal(record, member.member_id)
        return record

    @with_denial_log
    def reject(        self, actor_user_id: str, ledger_id: str, record_id: str, reason: str
    ) -> Record:
        """驳回一条待审核记录，必须填写驳回原因。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :param record_id: 记录标识。
        :param reason: 驳回原因，必填。
        :return: 更新后的记录。
        :raises ValidationError: 未填写驳回原因。
        :raises StateConflictError: 记录状态已变更。
        """
        member = self.access.require_admin(ledger_id, actor_user_id)
        text = (reason or "").strip()
        if not text:
            raise ValidationError("必须填写驳回原因")
        record = self._require_pending(ledger_id, record_id)

        StateGuard.assert_record_transition(
            record.status, RecordStatus.REJECTED, subject="记录"
        )

        previous = record.status
        record.status = RecordStatus.REJECTED
        record.reviewed_at = datetime.now()
        record.reviewer_id = member.member_id
        record.version = OptimisticLock.next_version(record.version)

        with self.repos.database.transaction():
            self.repos.records.save(record)
            self._write_trace(
                record,
                LogActionType.RECORD_REJECT,
                member.member_id,
                text,
                previous,
            )
            self.logs.append_params(
                ledger_id,
                member.member_id,
                LogActionType.RECORD_REJECT,
                "收支记录",
                record.record_id,
                {"金额": str(record.amount), "驳回原因": text},
            )
        return record

    @with_denial_log
    def void_record(
        self, actor_user_id: str, ledger_id: str, record_id: str, reason: str
    ) -> Record:
        """作废一条待审核或已通过的记录，必须填写作废原因。

        作废是终态：记录仍保留在列表中可查可追溯，但不再计入统计，
        也不能再次作废或被冲正（REQ-012、REQ-015）。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :param record_id: 记录标识。
        :param reason: 作废原因，必填。
        :return: 更新后的记录。
        :raises ValidationError: 未填写作废原因。
        :raises StateConflictError: 记录状态已变更。
        """
        member = self.access.require_admin(ledger_id, actor_user_id)
        text = (reason or "").strip()
        if not text:
            raise ValidationError("必须填写作废原因")
        record = self._require_voidable(ledger_id, record_id)

        StateGuard.assert_record_transition(
            record.status, RecordStatus.VOIDED, subject="记录"
        )

        previous = record.status
        record.status = RecordStatus.VOIDED
        record.reviewed_at = datetime.now()
        record.reviewer_id = member.member_id
        record.version = OptimisticLock.next_version(record.version)

        with self.repos.database.transaction():
            self.repos.records.save(record)
            self._write_trace(
                record, LogActionType.RECORD_VOID, member.member_id, text, previous
            )
            self.logs.append_params(
                ledger_id,
                member.member_id,
                LogActionType.RECORD_VOID,
                "收支记录",
                record.record_id,
                {"金额": str(record.amount), "作废原因": text},
            )
        return record

    def _require_pending(self, ledger_id: str, record_id: str) -> Record:
        """查找待审核记录。

        :param ledger_id: 账本标识。
        :param record_id: 记录标识。
        :return: 记录实体。
        :raises BusinessRuleError: 记录不存在或不属于该账本。
        :raises StateConflictError: 记录当前状态不是待审核。
        """
        record = self.repos.records.find_by_id(record_id)
        if record is None or record.ledger_id != ledger_id:
            raise BusinessRuleError("记录不存在")
        if record.status is not RecordStatus.PENDING:
            raise StateConflictError(
                "记录状态已变更，请刷新",
                f"当前状态 {record.status.display_name} 不是待审核",
            )
        return record

    def _require_voidable(self, ledger_id: str, record_id: str) -> Record:
        """查找可作废的记录。

        待审核与已通过的记录都可以作废，已作废与已冲正是终态不可再流转
        （REQ-012、REQ-015）。

        :param ledger_id: 账本标识。
        :param record_id: 记录标识。
        :return: 记录实体。
        :raises BusinessRuleError: 记录不存在或不属于该账本。
        :raises StateConflictError: 记录当前状态不允许作废。
        """
        record = self.repos.records.find_by_id(record_id)
        if record is None or record.ledger_id != ledger_id:
            raise BusinessRuleError("记录不存在")
        if record.status not in (RecordStatus.PENDING, RecordStatus.APPROVED):
            raise StateConflictError(
                "记录状态已变更，请刷新",
                f"当前状态 {record.status.display_name} 不允许作废",
            )
        return record

    def _write_trace(
        self,
        record: Record,
        action: LogActionType,
        actor_member_id: str,
        reason: str,
        previous: RecordStatus,
    ) -> None:
        """写入一条记录状态历史。

        :param record: 记录实体。
        :param action: 操作类型。
        :param actor_member_id: 操作人标识。
        :param reason: 变更原因。
        :param previous: 原状态。
        """
        self.repos.traces.save(
            RecordTrace(
                trace_id=new_uuid(),
                record_id=record.record_id,
                action=action,
                actor_id=actor_member_id,
                reason=reason,
                from_status=previous,
                to_status=record.status,
                occurred_at=datetime.now(),
            )
        )

    def _apply_reversal(self, reversal: Record, actor_member_id: str) -> None:
        """冲正记录审核通过时，把原记录置为已冲正。

        冲正记录与原记录成对出现，在统计中净额相抵（REQ-013）。

        :param reversal: 已通过的冲正记录。
        :param actor_member_id: 操作人标识。
        """
        apply_reversal_effect(self.repos, reversal, actor_member_id)

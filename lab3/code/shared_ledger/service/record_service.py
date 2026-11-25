"""收支记录服务。

对应实验二组件图中的记录与审核模块 `RecordService`，是整个系统的业务枢纽：
草稿保存、编辑、提交、撤回、查询、详情与冲正都归它。

状态合法由支撑层的 ``StateGuard`` 统一把关，不在每个方法里各写一遍
（REQ-015）。金额与分摊规则由 ``AmountAllocator`` 统一把关（REQ-017 ~ REQ-020）。
幂等去重由 ``IdempotentGuard`` 统一把关（REQ-035）。
并发编辑由 ``OptimisticLock`` 统一把关（REQ-037）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional

from ..domain.entities import Record, RecordTrace, ShareItem
from ..domain.enums import (
    CategoryStatus,
    LogActionType,
    MemberStatus,
    RecordStatus,
    RecordType,
    Role,
)
from ..domain.errors import BusinessRuleError, NotFoundError
from ..domain.support_ids import new_sequential_id, new_uuid
from ..persistence.repositories import Page, RecordFilter, RepositoryRegistry
from ..support.amount_allocator import AmountAllocator, Participant
from ..support.idempotent_guard import IdempotentGuard
from ..support.optimistic_lock import OptimisticLock
from ..support.state_guard import StateGuard
from .base import BaseService, with_denial_log
from .reversal import apply_reversal_effect


@dataclass
class RecordDraftInput:
    """录入或编辑一条记录所需的全部输入。

    对应实验二 UI 原型「记一笔」表单的字段集合：
    收支类型、金额、分类、记账日期、付款人、备注与分摊成员。
    """

    record_type: RecordType = RecordType.EXPENSE
    amount: Decimal = Decimal("0.00")
    category_id: str = ""
    record_date: date = field(default_factory=date.today)
    note: str = ""
    payer_member_id: str = ""
    participant_member_ids: List[str] = field(default_factory=list)


@dataclass
class RecordDetail:
    """记录详情视图所需的全部数据。"""

    record: Record
    shares: List[ShareItem] = field(default_factory=list)
    traces: List[RecordTrace] = field(default_factory=list)
    available_actions: List[str] = field(default_factory=list)
    reversal: Optional[Record] = None
    reversed_by: Optional[Record] = None


class RecordService(BaseService):
    """收支记录服务。"""

    def __init__(
        self,
        repos: RepositoryRegistry,
        access: Any,
        logs: Any = None,
        idempotent: Optional[IdempotentGuard] = None,
    ) -> None:
        """初始化服务。

        :param repos: 仓储集合。
        :param access: 权限守卫。
        :param logs: 日志服务。
        :param idempotent: 幂等守卫。
        """
        super().__init__(repos, access, logs)
        self.idempotent = idempotent

    @with_denial_log
    def create_draft(
        self,
        actor_user_id: str,
        ledger_id: str,
        payload: RecordDraftInput,
        request_id: str = "",
    ) -> Record:
        """录入一条记录并存为草稿。

        :param actor_user_id: 操作者，必须是记账成员或管理员。
        :param ledger_id: 账本标识。
        :param payload: 记录内容。
        :param request_id: 客户端请求标识，用于重复提交去重。
        :return: 新建的草稿记录。
        :raises ValidationError: 金额、分类、付款人或分摊成员不合法。
        """
        self.access.require_writer(ledger_id, actor_user_id)

        if request_id and self.idempotent is not None:
            existing = self.idempotent.lookup(request_id, datetime.now())
            if existing:
                found = self.repos.records.find_by_id(existing)
                if found is not None:
                    return found

        self._require_enabled_category(ledger_id, payload.category_id)
        amount = AmountAllocator.validate_amount(
            payload.amount, check_limit=False
        )
        payer = self._require_writable_member(ledger_id, payload.payer_member_id)
        participants = self._require_participants(
            ledger_id, payload.participant_member_ids
        )

        now = datetime.now()
        record = Record(
            record_id=new_sequential_id("R", now=now),
            ledger_id=ledger_id,
            creator_id=actor_user_id,
            payer_id=payer.member_id,
            category_id=payload.category_id,
            type=payload.record_type,
            amount=amount,
            record_date=payload.record_date,
            note=payload.note,
            status=RecordStatus.DRAFT,
            version=1,
            request_id=request_id,
            created_at=now,
        )
        allocations = AmountAllocator.split_evenly(
            amount, self._to_participants(participants)
        )
        AmountAllocator.validate_share_sum(
            amount, [item.amount for item in allocations]
        )

        with self.repos.database.transaction():
            self.repos.records.save(record)
            self.repos.shares.replace_for_record(
                record.record_id, self._to_share_items(record.record_id, allocations)
            )
            if request_id and self.idempotent is not None:
                self.idempotent.remember(
                    request_id, actor_user_id, record.record_id, now
                )
        return record

    @with_denial_log
    def update_draft(
        self,
        actor_user_id: str,
        ledger_id: str,
        record_id: str,
        payload: RecordDraftInput,
        expected_version: Optional[int] = None,
    ) -> Record:
        """编辑草稿或已驳回的记录。

        :param actor_user_id: 操作者，必须是记录的录入人。
        :param ledger_id: 账本标识。
        :param record_id: 记录标识。
        :param payload: 新的记录内容。
        :param expected_version: 客户端持有的版本号。
        :return: 更新后的记录。
        :raises StateConflictError: 记录当前状态不允许编辑。
        """
        self.access.require_active_member(ledger_id, actor_user_id)
        record = self._require_record(ledger_id, record_id)
        self._require_creator(record, actor_user_id, ledger_id)

        if record.status not in (RecordStatus.DRAFT, RecordStatus.REJECTED):
            raise BusinessRuleError("只有草稿或已驳回的记录可以编辑")

        OptimisticLock.assert_version(expected_version, record.version)

        self._require_enabled_category(ledger_id, payload.category_id)
        amount = AmountAllocator.validate_amount(
            payload.amount, check_limit=False
        )
        payer = self._require_writable_member(ledger_id, payload.payer_member_id)
        participants = self._require_participants(
            ledger_id, payload.participant_member_ids
        )
        allocations = AmountAllocator.split_evenly(
            amount, self._to_participants(participants)
        )
        AmountAllocator.validate_share_sum(
            amount, [item.amount for item in allocations]
        )

        record.payer_id = payer.member_id
        record.category_id = payload.category_id
        record.type = payload.record_type
        record.amount = amount
        record.record_date = payload.record_date
        record.note = payload.note
        record.status = RecordStatus.DRAFT
        record.version = OptimisticLock.next_version(record.version)

        with self.repos.database.transaction():
            self.repos.records.save(record)
            self.repos.shares.replace_for_record(
                record.record_id, self._to_share_items(record.record_id, allocations)
            )
        return record

    @with_denial_log
    def submit(
        self,
        actor_user_id: str,
        ledger_id: str,
        record_id: str,
        request_id: str = "",
        expected_version: Optional[int] = None,
    ) -> Record:
        """提交记录进入审核。

        管理员本人录入的记录提交后直接置为已通过，即自审豁免（REQ-016）。

        :param actor_user_id: 操作者，必须是记录录入人。
        :param ledger_id: 账本标识。
        :param record_id: 记录标识。
        :param request_id: 客户端请求标识。
        :param expected_version: 客户端持有的版本号。
        :return: 提交后的记录。
        :raises StateConflictError: 记录当前状态不允许提交。
        :raises ValidationError: 金额超出单笔限额。
        """
        member = self.access.require_active_member(ledger_id, actor_user_id)
        record = self._require_record(ledger_id, record_id)
        self._require_creator(record, actor_user_id, ledger_id)

        # 幂等查重必须排在状态校验与版本校验之前：
        # 提交动作被重复触发时，要按 REQ-035 返回首次提交的结果，
        # 而不是先被状态校验拦下、也不是先被版本校验拦下。
        # 只有当查到的记录仍处于可提交状态（草稿或已驳回）时，
        # 才说明这个标识此前是用于「新建」而不是用于「提交」，此时继续走提交流程。
        if request_id and self.idempotent is not None:
            existing = self.idempotent.lookup(request_id, datetime.now())
            if existing:
                found = self.repos.records.find_by_id(existing)
                if found is not None and found.status not in (
                    RecordStatus.DRAFT,
                    RecordStatus.REJECTED,
                ):
                    return found

        if record.status not in (RecordStatus.DRAFT, RecordStatus.REJECTED):
            raise BusinessRuleError("只有草稿或已驳回的记录可以提交审核")

        OptimisticLock.assert_version(expected_version, record.version)
        AmountAllocator.validate_amount(record.amount, check_limit=True)

        self_review = member.role is Role.ADMIN
        target = RecordStatus.APPROVED if self_review else RecordStatus.PENDING
        StateGuard.assert_record_transition(record.status, target)

        now = datetime.now()
        previous = record.status
        record.status = target
        record.submitted_at = now
        record.version = OptimisticLock.next_version(record.version)
        if request_id:
            record.request_id = request_id

        with self.repos.database.transaction():
            self.repos.records.save(record)
            self._write_trace(
                record, LogActionType.RECORD_SUBMIT, member.member_id, "", previous, target
            )
            action = (
                LogActionType.SELF_REVIEW if self_review else LogActionType.RECORD_SUBMIT
            )
            self.logs.append_params(
                ledger_id,
                member.member_id,
                action,
                "收支记录",
                record.record_id,
                {
                    "金额": str(record.amount),
                    "类型": record.type.display_name,
                    "状态": f"{previous.display_name} → {target.display_name}",
                },
            )
            if request_id and self.idempotent is not None:
                self.idempotent.remember(
                    request_id, actor_user_id, record.record_id, now
                )
            if self_review and record.reversal_of_id:
                apply_reversal_effect(self.repos, record, member.member_id)
        return record

    @with_denial_log
    def withdraw(self, actor_user_id: str, ledger_id: str, record_id: str) -> Record:
        """记录人撤回自己处于待审核状态的记录。

        管理员不能使用撤回，只能通过驳回处理待审核记录（REQ-011）。

        :param actor_user_id: 操作者，必须是记录录入人。
        :param ledger_id: 账本标识。
        :param record_id: 记录标识。
        :return: 撤回后的记录。
        :raises StateConflictError: 记录状态已变更。
        """
        member = self.access.require_active_member(ledger_id, actor_user_id)
        record = self._require_record(ledger_id, record_id)
        self._require_creator(record, actor_user_id, ledger_id)

        StateGuard.assert_record_transition(
            record.status, RecordStatus.DRAFT, subject="记录"
        )

        previous = record.status
        record.status = RecordStatus.DRAFT
        record.submitted_at = None
        record.version = OptimisticLock.next_version(record.version)

        with self.repos.database.transaction():
            self.repos.records.save(record)
            self._write_trace(
                record,
                LogActionType.RECORD_WITHDRAW,
                member.member_id,
                "",
                previous,
                RecordStatus.DRAFT,
            )
            self.logs.append_params(
                ledger_id,
                member.member_id,
                LogActionType.RECORD_WITHDRAW,
                "收支记录",
                record.record_id,
                {"状态": f"{previous.display_name} → 草稿"},
            )
        return record

    @with_denial_log
    def query_records(
        self, actor_user_id: str, ledger_id: str, criteria: RecordFilter
    ) -> Page:
        """按多条件组合分页查询记录。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :param criteria: 查询条件。
        :return: 分页结果。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        return self.repos.records.query(ledger_id, criteria.normalized())

    @with_denial_log
    def get_detail(
        self, actor_user_id: str, ledger_id: str, record_id: str
    ) -> RecordDetail:
        """查看记录详情、分摊明细与状态历史。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :param record_id: 记录标识。
        :return: 记录详情。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        record = self._require_record(ledger_id, record_id)
        detail = RecordDetail(
            record=record,
            shares=self.repos.shares.list_by_record(record_id),
            traces=self.repos.traces.list_by_record(record_id),
            available_actions=StateGuard.available_record_actions(record.status),
        )
        if record.reversal_of_id:
            detail.reversal = self.repos.records.find_by_id(record.reversal_of_id)
        if record.reversed_by_id:
            detail.reversed_by = self.repos.records.find_by_id(record.reversed_by_id)
        return detail

    @with_denial_log
    def create_reversal(
        self, actor_user_id: str, ledger_id: str, record_id: str
    ) -> Record:
        """对已通过记录发起冲正更正。

        冲正记录与原记录类型相同、金额相同，分摊明细镜像原记录，
        记账日期沿用原记录以便两者落在同一统计月份。
        冲正记录按新记录流程提交审核，审核通过后原记录才变为已冲正。

        :param actor_user_id: 操作者，必须是记录录入人或管理员。
        :param ledger_id: 账本标识。
        :param record_id: 原记录标识。
        :return: 新建的冲正记录。
        :raises StateConflictError: 原记录状态不允许冲正。
        :raises BusinessRuleError: 已存在待审核的冲正记录。
        """
        member = self.access.require_active_member(ledger_id, actor_user_id)
        original = self._require_record(ledger_id, record_id)
        if original.status is not RecordStatus.APPROVED:
            raise BusinessRuleError("只有已通过的记录可以发起冲正")
        if original.creator_id != actor_user_id and member.role is not Role.ADMIN:
            self.access.deny(
                ledger_id,
                actor_user_id,
                "收支记录",
                record_id,
                "只能对本人录入的记录发起冲正",
            )
        if original.reversal_of_id:
            raise BusinessRuleError("冲正记录不能再发起冲正")
        if self._find_pending_reversal(ledger_id, record_id) is not None:
            raise BusinessRuleError("该记录已有待审核的冲正记录")

        shares = self.repos.shares.list_by_record(record_id)
        now = datetime.now()
        reversal = Record(
            record_id=new_sequential_id("R", now=now),
            ledger_id=ledger_id,
            creator_id=actor_user_id,
            payer_id=original.payer_id,
            category_id=original.category_id,
            type=original.type,
            amount=original.amount,
            record_date=original.record_date,
            note=f"冲正原记录 {original.record_id}",
            status=RecordStatus.DRAFT,
            version=1,
            reversal_of_id=original.record_id,
            created_at=now,
        )
        mirrored = [
            ShareItem(
                share_id=new_uuid(),
                record_id=reversal.record_id,
                member_id=item.member_id,
                amount=item.amount,
                is_remainder_holder=item.is_remainder_holder,
            )
            for item in shares
        ]

        with self.repos.database.transaction():
            self.repos.records.save(reversal)
            self.repos.shares.replace_for_record(reversal.record_id, mirrored)
            self.logs.append_params(
                ledger_id,
                member.member_id,
                LogActionType.RECORD_REVERSE,
                "收支记录",
                reversal.record_id,
                {
                    "冲正原记录": original.record_id,
                    "金额": str(original.amount),
                    "类型": original.type.display_name,
                },
            )
        return reversal

    def list_pending(self, ledger_id: str) -> List[Record]:
        """列出账本内待审核的记录，供管理员审核界面使用。

        :param ledger_id: 账本标识。
        :return: 待审核记录列表。
        """
        return self.repos.records.list_by_status(ledger_id, RecordStatus.PENDING)

    def list_drafts(self, actor_user_id: str, ledger_id: str) -> List[Record]:
        """列出当前用户的草稿记录。

        :param actor_user_id: 操作者。
        :param ledger_id: 账本标识。
        :return: 草稿记录列表。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        drafts = []
        for record in self.repos.records.list_by_status(
            ledger_id, RecordStatus.DRAFT
        ):
            if record.creator_id == actor_user_id:
                drafts.append(record)
        return drafts

    def _require_record(self, ledger_id: str, record_id: str) -> Record:
        """按标识查找记录并校验其属于指定账本。

        :param ledger_id: 账本标识。
        :param record_id: 记录标识。
        :return: 记录实体。
        :raises NotFoundError: 记录不存在或不属于该账本。
        """
        record = self.repos.records.find_by_id(record_id)
        if record is None or record.ledger_id != ledger_id:
            raise NotFoundError("记录不存在")
        return record

    def _require_creator(
        self, record: Record, actor_user_id: str, ledger_id: str
    ) -> None:
        """校验操作者是记录录入人。

        :param record: 记录实体。
        :param actor_user_id: 操作者。
        :param ledger_id: 账本标识。
        :raises PermissionDeniedError: 操作者不是录入人。
        """
        if record.creator_id != actor_user_id:
            self.access.deny(
                ledger_id,
                actor_user_id,
                "收支记录",
                record.record_id,
                "只能操作本人录入的记录",
            )

    def _require_enabled_category(self, ledger_id: str, category_id: str) -> None:
        """校验分类存在、属于本账本且处于启用状态。

        :param ledger_id: 账本标识。
        :param category_id: 分类标识。
        :raises BusinessRuleError: 分类不存在或已停用。
        """
        category = self.repos.categories.find_by_id(category_id)
        if category is None or category.ledger_id != ledger_id:
            raise BusinessRuleError("分类不存在")
        if category.status is CategoryStatus.DISABLED:
            raise BusinessRuleError("该分类已停用，不能再用于新记录")

    def _require_writable_member(self, ledger_id: str, member_id: str) -> Any:
        """校验成员可以充当付款人或分摊人。

        只读成员不能作为付款人，也不能参与分摊（REQ-019）。

        :param ledger_id: 账本标识。
        :param member_id: 成员标识。
        :return: 成员关系。
        :raises BusinessRuleError: 成员不存在、已退出或为只读角色。
        """
        member = self.repos.members.find_by_id(member_id)
        if member is None or member.ledger_id != ledger_id:
            raise BusinessRuleError("成员不存在")
        if member.status is not MemberStatus.ACTIVE:
            raise BusinessRuleError("已退出的成员不能参与记账")
        if not member.role.can_write_record:
            raise BusinessRuleError("只读成员不能作为付款人或参与分摊")
        return member

    def _require_participants(self, ledger_id: str, member_ids: List[str]) -> List:
        """校验分摊成员列表。

        :param ledger_id: 账本标识。
        :param member_ids: 成员标识列表。
        :return: 成员关系列表。
        :raises BusinessRuleError: 列表为空或存在重复人员。
        """
        if not member_ids:
            raise BusinessRuleError("至少需要一名成员参与分摊")
        if len(set(member_ids)) != len(member_ids):
            raise BusinessRuleError("参与分摊的成员中出现重复人员")
        return [self._require_writable_member(ledger_id, item) for item in member_ids]

    @staticmethod
    def _to_participants(members: List) -> List[Participant]:
        """把成员关系转成分摊算法需要的参与者结构。

        :param members: 成员关系列表。
        :return: 参与者列表。
        """
        return [
            Participant(member_id=member.member_id, joined_at=member.joined_at)
            for member in members
        ]

    @staticmethod
    def _to_share_items(record_id: str, allocations: List) -> List[ShareItem]:
        """把分摊结果转成可持久化的分摊明细。

        :param record_id: 记录标识。
        :param allocations: 分摊结果。
        :return: 分摊明细列表。
        """
        return [
            ShareItem(
                share_id=new_uuid(),
                record_id=record_id,
                member_id=item.member_id,
                amount=item.amount,
                is_remainder_holder=item.is_remainder_holder,
            )
            for item in allocations
        ]

    def _find_pending_reversal(
        self, ledger_id: str, record_id: str
    ) -> Optional[Record]:
        """查找某条记录尚未审核完成的冲正记录。

        :param ledger_id: 账本标识。
        :param record_id: 原记录标识。
        :return: 冲正记录，不存在时返回 ``None``。
        """
        for record in self.repos.records.list_by_ledger(ledger_id):
            if record.reversal_of_id != record_id:
                continue
            if record.status in (RecordStatus.DRAFT, RecordStatus.PENDING):
                return record
        return None

    def _write_trace(
        self,
        record: Record,
        action: LogActionType,
        actor_member_id: str,
        reason: str,
        from_status: RecordStatus,
        to_status: RecordStatus,
    ) -> RecordTrace:
        """写入一条记录状态历史。

        :param record: 记录实体。
        :param action: 操作类型。
        :param actor_member_id: 操作人标识。
        :param reason: 变更原因。
        :param from_status: 原状态。
        :param to_status: 新状态。
        :return: 写入的历史实体。
        """
        trace = RecordTrace(
            trace_id=new_uuid(),
            record_id=record.record_id,
            action=action,
            actor_id=actor_member_id,
            reason=reason,
            from_status=from_status,
            to_status=to_status,
            occurred_at=datetime.now(),
        )
        self.repos.traces.save(trace)
        return trace

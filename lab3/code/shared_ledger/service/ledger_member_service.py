"""账本与成员服务。

对应实验二组件图中的账本与成员模块 `LedgerMemberService`。

覆盖 REQ-001 至 REQ-006：

- 创建账本并把创建者设为唯一管理员，同时铺好系统默认分类；
- 调整成员角色；
- 成员退出或被管理员移除，历史记录保留但不再参与后续结算；
- 已退出成员重新加入后结算资格失效，需管理员显式恢复。

一条重要边界：管理员角色不可转让（REQ-046 明确不实现），
因此本服务不存在「把管理员降级」的操作入口。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from ..domain.entities import Category, DEFAULT_CATEGORY_NAMES, Ledger, LedgerMember
from ..domain.enums import CategoryStatus, LogActionType, MemberStatus, RecordStatus, Role
from ..domain.errors import BusinessRuleError, ValidationError
from ..domain.support_ids import new_uuid
from ..persistence.repositories import RepositoryRegistry
from .base import BaseService, with_denial_log


@dataclass
class LedgerSummary:
    """账本列表卡片所需的汇总信息。"""

    ledger: Ledger
    member: LedgerMember
    member_count: int = 0
    pending_count: int = 0
    month_expense: Decimal = Decimal("0.00")
    month_income: Decimal = Decimal("0.00")


@dataclass
class MemberSummary:
    """成员管理页所需的成员信息。"""

    member: LedgerMember
    record_count: int = 0
    net_amount: Decimal = Decimal("0.00")


class LedgerMemberService(BaseService):
    """账本与成员服务。"""

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
    def create_ledger(self, creator_user_id: str, ledger_name: str) -> Ledger:
        """创建账本，创建者自动成为唯一管理员。

        :param creator_user_id: 创建者用户标识。
        :param ledger_name: 账本名称。
        :return: 新建的账本实体。
        :raises ValidationError: 账本名称为空或过长。
        """
        name = (ledger_name or "").strip()
        if not name:
            raise ValidationError("账本名称不能为空")
        if len(name) > 30:
            raise ValidationError("账本名称过长")

        now = datetime.now()
        member = LedgerMember(
            member_id=new_uuid(),
            user_id=creator_user_id,
            ledger_id="",
            role=Role.ADMIN,
            status=MemberStatus.ACTIVE,
            joined_at=now,
            settlement_eligible=True,
        )
        ledger = Ledger(
            ledger_id=new_uuid(),
            name=name,
            admin_member_id=member.member_id,
            created_at=now,
        )
        member.ledger_id = ledger.ledger_id

        with self.repos.database.transaction():
            self.repos.ledgers.save(ledger)
            self.repos.members.save(member)
            self._create_default_categories(ledger.ledger_id, now)
        self.logs.append_params(
            ledger.ledger_id,
            member.member_id,
            LogActionType.MEMBER_JOIN,
            "账本",
            ledger.ledger_id,
            {"账本": ledger.name, "创建者自动成为管理员": True},
        )
        return ledger

    @with_denial_log
    def list_ledgers_for_user(self, user_id: str) -> List[LedgerSummary]:
        """列出用户参与的账本。

        :param user_id: 用户标识。
        :return: 账本汇总列表。
        """
        summaries: List[LedgerSummary] = []
        for member in self.repos.members.list_by_user(user_id):
            ledger = self.repos.ledgers.find_by_id(member.ledger_id)
            if ledger is None:
                continue
            summaries.append(self._summarize(ledger, member))
        return summaries

    def get_ledger(self, ledger_id: str) -> Ledger:
        """按标识查找账本。

        :param ledger_id: 账本标识。
        :return: 账本实体。
        :raises BusinessRuleError: 账本不存在。
        """
        ledger = self.repos.ledgers.find_by_id(ledger_id)
        if ledger is None:
            raise BusinessRuleError("账本不存在")
        return ledger

    @with_denial_log
    def list_members(self, actor_user_id: str, ledger_id: str) -> List[MemberSummary]:
        """列出账本内全部成员。

        :param actor_user_id: 操作者。
        :param ledger_id: 账本标识。
        :return: 成员汇总列表。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        result: List[MemberSummary] = []
        for member in self.repos.members.list_by_ledger(ledger_id):
            result.append(self._member_summary(member))
        return result

    @with_denial_log
    def change_role(
        self,
        actor_user_id: str,
        ledger_id: str,
        target_user_id: str,
        new_role: Role,
    ) -> LedgerMember:
        """调整成员角色。

        只读成员与记账成员之间可以互调，但管理员行不可被调整，
        因为本版本不支持管理员角色转让（REQ-046）。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :param target_user_id: 被调整的用户标识。
        :param new_role: 目标角色。
        :return: 更新后的成员关系。
        :raises BusinessRuleError: 目标不存在或目标是管理员。
        """
        self.access.require_admin(ledger_id, actor_user_id)
        target = self.repos.members.find(ledger_id, target_user_id)
        if target is None:
            raise BusinessRuleError("该成员不在本账本中")
        if target.role is Role.ADMIN:
            raise BusinessRuleError("管理员角色不可转让")
        if new_role is Role.ADMIN:
            raise BusinessRuleError("不支持新增管理员")
        if target.role is new_role:
            return target

        old_role = target.role
        target.role = new_role
        target.settlement_eligible = new_role is not Role.READER
        self.repos.members.save(target)
        self.logs.append_params(
            ledger_id,
            target.member_id,
            LogActionType.ROLE_CHANGE,
            "账本成员",
            target.member_id,
            {
                "成员": target.display_name,
                "原角色": old_role.display_name,
                "新角色": new_role.display_name,
            },
        )
        return target

    @with_denial_log
    def remove_member(
        self, actor_user_id: str, ledger_id: str, target_user_id: str
    ) -> LedgerMember:
        """把成员移出账本。

        被移除成员的记录仍保留在账本中且归属不变，
        该成员不再参与后续结算（REQ-005）。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :param target_user_id: 被移除的用户标识。
        :return: 更新后的成员关系。
        :raises BusinessRuleError: 目标是管理员。
        """
        self.access.require_admin(ledger_id, actor_user_id)
        target = self.repos.members.find(ledger_id, target_user_id)
        if target is None:
            raise BusinessRuleError("该成员不在本账本中")
        if target.role is Role.ADMIN:
            raise BusinessRuleError("管理员不能被移除")

        target.status = MemberStatus.LEFT
        target.settlement_eligible = False
        self.repos.members.save(target)
        self.logs.append_params(
            ledger_id,
            target.member_id,
            LogActionType.MEMBER_LEAVE,
            "账本成员",
            target.member_id,
            {"成员": target.display_name, "方式": "被管理员移出账本"},
        )
        return target

    @with_denial_log
    def leave_ledger(self, actor_user_id: str, ledger_id: str) -> LedgerMember:
        """成员自行退出账本。

        已生成的结算单不因成员退出而改动（REQ-005）。

        :param actor_user_id: 操作者。
        :param ledger_id: 账本标识。
        :return: 更新后的成员关系。
        :raises BusinessRuleError: 管理员不能退出。
        """
        member = self.access.require_active_member(ledger_id, actor_user_id)
        if member.role is Role.ADMIN:
            raise BusinessRuleError("管理员不能退出账本")
        member.status = MemberStatus.LEFT
        member.settlement_eligible = False
        self.repos.members.save(member)
        self.logs.append_params(
            ledger_id,
            member.member_id,
            LogActionType.MEMBER_LEAVE,
            "账本成员",
            member.member_id,
            {"成员": member.display_name, "方式": "自行退出账本"},
        )
        return member

    @with_denial_log
    def restore_settlement_eligibility(
        self, actor_user_id: str, ledger_id: str, target_user_id: str
    ) -> LedgerMember:
        """恢复成员的结算资格。

        已退出或被移除的成员重新加入后不自动参与新的结算，
        需要管理员显式恢复（REQ-006）。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :param target_user_id: 目标用户标识。
        :return: 更新后的成员关系。
        :raises BusinessRuleError: 目标不存在或为只读角色。
        """
        self.access.require_admin(ledger_id, actor_user_id)
        target = self.repos.members.find(ledger_id, target_user_id)
        if target is None:
            raise BusinessRuleError("该成员不在本账本中")
        if target.role is Role.READER:
            raise BusinessRuleError("只读成员本就不参与结算")
        target.settlement_eligible = True
        self.repos.members.save(target)
        self.logs.append_params(
            ledger_id,
            target.member_id,
            LogActionType.ROLE_CHANGE,
            "账本成员",
            target.member_id,
            {"成员": target.display_name, "结算资格": "已恢复"},
        )
        return target

    def member_of(self, ledger_id: str, user_id: str) -> Optional[LedgerMember]:
        """查询用户在账本中的成员关系。

        :param ledger_id: 账本标识。
        :param user_id: 用户标识。
        :return: 成员关系，不存在时返回 ``None``。
        """
        return self.repos.members.find(ledger_id, user_id)

    def _summarize(self, ledger: Ledger, member: LedgerMember) -> LedgerSummary:
        """构造账本汇总信息。

        :param ledger: 账本实体。
        :param member: 当前用户的成员关系。
        :return: 汇总信息。
        """
        summary = LedgerSummary(
            ledger=ledger,
            member=member,
            member_count=self.repos.members.count_active(ledger.ledger_id),
        )
        month_prefix = datetime.now().strftime("%Y-%m")
        for record in self.repos.records.list_by_status(
            ledger.ledger_id, RecordStatus.APPROVED
        ):
            if not record.record_date.isoformat().startswith(month_prefix):
                continue
            if record.type.value == "EXPENSE":
                summary.month_expense += record.amount
            else:
                summary.month_income += record.amount
        summary.pending_count = len(
            self.repos.records.list_by_status(ledger.ledger_id, RecordStatus.PENDING)
        )
        return summary

    def _member_summary(self, member: LedgerMember) -> MemberSummary:
        """构造成员汇总信息。

        :param member: 成员关系。
        :return: 汇总信息。
        """
        summary = MemberSummary(member=member)
        for record in self.repos.records.list_by_ledger(member.ledger_id):
            if record.creator_id != member.user_id:
                continue
            summary.record_count += 1
            summary.net_amount += record.signed_amount
        return summary

    def _create_default_categories(self, ledger_id: str, now: datetime) -> None:
        """为新账本铺好系统默认分类。

        :param ledger_id: 账本标识。
        :param now: 创建时间。
        """
        for name in DEFAULT_CATEGORY_NAMES:
            self.repos.categories.save(
                Category(
                    category_id=new_uuid(),
                    ledger_id=ledger_id,
                    name=name,
                    is_default=True,
                    status=CategoryStatus.ENABLED,
                    created_at=now,
                )
            )

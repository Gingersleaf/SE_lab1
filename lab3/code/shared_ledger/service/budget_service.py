"""预算服务。

对应实验二组件图中的统计与预算模块 `BudgetService`。

覆盖 REQ-028 与 REQ-029：管理员可设置账本总预算与分类预算；
已用金额达到预算金额的九成时在概览页高亮提示。

预算的已用金额直接取自统计服务的口径，不另算一套，
否则统计口径一旦被改坏，预算进度会与分类统计对不上。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from ..domain.entities import Budget
from ..domain.enums import LogActionType
from ..domain.errors import BusinessRuleError, ValidationError
from ..domain.support_ids import new_uuid
from ..persistence.repositories import RepositoryRegistry
from ..support.amount_allocator import AmountAllocator
from .base import BaseService, with_denial_log

LEVEL_NORMAL = "正常"
LEVEL_WARNING = "接近上限"
LEVEL_OVER = "已超支"


@dataclass
class BudgetProgress:
    """一条预算的执行进度。"""

    budget: Budget
    used: Decimal = Decimal("0.00")
    remaining: Decimal = Decimal("0.00")
    ratio: float = 0.0
    level: str = LEVEL_NORMAL
    category_name: str = ""


class BudgetService(BaseService):
    """预算服务。"""

    def __init__(
        self,
        repos: RepositoryRegistry,
        access: Any,
        logs: Any = None,
        statistics: Any = None,
    ) -> None:
        """初始化服务。

        :param repos: 仓储集合。
        :param access: 权限守卫。
        :param logs: 日志服务。
        :param statistics: 统计服务，用于计算已用金额。
        """
        super().__init__(repos, access, logs)
        self.statistics = statistics

    @with_denial_log
    def list_budgets(self, actor_user_id: str, ledger_id: str) -> List[Budget]:
        """列出账本内的全部预算。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :return: 预算列表。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        return self.repos.budgets.list_by_ledger(ledger_id)

    @with_denial_log
    def set_budget(
        self,
        actor_user_id: str,
        ledger_id: str,
        category_id: Optional[str],
        amount: Decimal,
        warning_ratio: Decimal = Decimal("0.9"),
    ) -> Budget:
        """设置账本总预算或分类预算。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :param category_id: 分类标识，为空表示账本总预算。
        :param amount: 预算金额，必须为正数。
        :param warning_ratio: 预警比例。
        :return: 设置后的预算。
        :raises ValidationError: 金额或预警比例不合法。
        """
        member = self.access.require_admin(ledger_id, actor_user_id)
        value = AmountAllocator.validate_budget_amount(amount)
        ratio = Decimal(str(warning_ratio))
        if ratio <= 0 or ratio > 1:
            raise ValidationError("预警比例必须大于零且不超过一")

        if category_id:
            category = self.repos.categories.find_by_id(category_id)
            if category is None or category.ledger_id != ledger_id:
                raise BusinessRuleError("分类不存在")

        existing = self.repos.budgets.find(ledger_id, category_id)
        if existing is None:
            existing = Budget(
                budget_id=new_uuid(),
                ledger_id=ledger_id,
                category_id=category_id or None,
                amount=value,
                warning_ratio=ratio,
                created_by=member.member_id,
                created_at=datetime.now(),
            )
        else:
            existing.amount = value
            existing.warning_ratio = ratio
        self.repos.budgets.save(existing)
        self.logs.append_params(
            ledger_id,
            member.member_id,
            LogActionType.RECORD_SUBMIT,
            "预算",
            existing.budget_id,
            {
                "操作": "设置预算",
                "范围": existing.category_name or "账本总预算",
                "金额": str(value),
            },
        )
        return existing

    @with_denial_log
    def budget_progress(
        self, actor_user_id: str, ledger_id: str, month: Optional[str] = None
    ) -> List[BudgetProgress]:
        """计算预算执行进度。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :param month: 统计月份，形如 ``2026-11``，默认为当月。
        :return: 预算进度列表。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        target = month or datetime.now().strftime("%Y-%m")
        budgets = self.repos.budgets.list_by_ledger(ledger_id)
        results: List[BudgetProgress] = []
        for budget in budgets:
            used = self._used_amount(ledger_id, budget, target)
            progress = BudgetProgress(
                budget=budget,
                used=used.quantize(Decimal("0.01")),
                remaining=(budget.amount - used).quantize(Decimal("0.01")),
                ratio=0.0,
                level=LEVEL_NORMAL,
                category_name=budget.category_name or "账本总预算",
            )
            if budget.amount > 0:
                progress.ratio = float(used / budget.amount)
            if used >= budget.amount:
                progress.level = LEVEL_OVER
            elif used >= budget.amount * budget.warning_ratio:
                progress.level = LEVEL_WARNING
            results.append(progress)
        return results

    def _used_amount(self, ledger_id: str, budget: Budget, month: str) -> Decimal:
        """计算一条预算在指定月份内的已用金额。

        :param ledger_id: 账本标识。
        :param budget: 预算实体。
        :param month: 统计月份。
        :return: 已用金额。
        """
        if self.statistics is None:
            return Decimal("0.00")
        used = Decimal("0.00")
        for entry in self.statistics.counted_entries(ledger_id):
            record = entry.record
            if record.type.value != "EXPENSE":
                continue
            if not record.record_date.isoformat().startswith(month):
                continue
            if budget.category_id and record.category_id != budget.category_id:
                continue
            used += record.amount * entry.direction
        return used

"""预算设置与执行进度的单元测试。

覆盖 REQ-028（预算设置）与 REQ-029（预算超支的高亮提示）。
"""

from __future__ import annotations

from decimal import Decimal

from shared_ledger.domain.errors import PermissionDeniedError, ValidationError
from shared_ledger.service.budget_service import (
    LEVEL_NORMAL,
    LEVEL_OVER,
    LEVEL_WARNING,
)

from tests.base import LedgerTestCase


class BudgetSettingTest(LedgerTestCase):
    """预算设置的用例。"""

    def test_预算金额必须为正数(self) -> None:
        """验证 REQ-028：预算金额为零或负数时不允许保存。"""
        with self.assertRaises(ValidationError) as ctx:
            self.ctx.budgets.set_budget(
                self.admin.user_id, self.ledger_id, None, Decimal("0")
            )
        self.assertIn("预算金额必须大于零", str(ctx.exception))
        with self.assertRaises(ValidationError):
            self.ctx.budgets.set_budget(
                self.admin.user_id, self.ledger_id, None, Decimal("-100.00")
            )

    def test_预算金额不受单笔上限约束(self) -> None:
        """验证 REQ-028：预算金额可超过记录的单笔 500000.00 元上限。"""
        budget = self.ctx.budgets.set_budget(
            self.admin.user_id, self.ledger_id, None, Decimal("600000.00")
        )
        self.assertEqual(budget.amount, Decimal("600000.00"))

    def test_预算金额超过两位小数被拒绝(self) -> None:
        """验证 REQ-028：预算金额同样精确到分，最多两位小数。"""
        with self.assertRaises(ValidationError) as ctx:
            self.ctx.budgets.set_budget(
                self.admin.user_id, self.ledger_id, None, Decimal("100.555")
            )
        self.assertIn("最多保留两位小数", str(ctx.exception))

    def test_总预算与分类预算都出现在执行进度中(self) -> None:
        """验证 REQ-028：总预算与分类预算设置后均出现在预算执行进度中。"""
        food = self.category("餐饮")
        self.ctx.budgets.set_budget(
            self.admin.user_id, self.ledger_id, None, Decimal("5000.00")
        )
        self.ctx.budgets.set_budget(
            self.admin.user_id, self.ledger_id, food.category_id, Decimal("500.00")
        )
        progress = self.ctx.budgets.budget_progress(
            self.admin.user_id, self.ledger_id, "2026-11"
        )
        self.assertEqual(len(progress), 2)
        names = {item.category_name for item in progress}
        self.assertIn("账本总预算", names)
        self.assertIn("餐饮", names)

    def test_只有管理员可以设置预算(self) -> None:
        """验证 REQ-028、REQ-044：非管理员设置预算被拒绝。"""
        with self.assertRaises(PermissionDeniedError):
            self.ctx.budgets.set_budget(
                self.writer.user_id, self.ledger_id, None, Decimal("5000.00")
            )


class BudgetProgressTest(LedgerTestCase):
    """预算执行进度的用例。"""

    def test_已用不足九成时保持正常(self) -> None:
        """验证 REQ-029：已用金额低于九成时预算保持常规样式。"""
        self.ctx.budgets.set_budget(
            self.admin.user_id, self.ledger_id, None, Decimal("1000.00")
        )
        self.make_approved(self.writer, "800.00")
        progress = self.ctx.budgets.budget_progress(
            self.admin.user_id, self.ledger_id, "2026-11"
        )
        self.assertEqual(len(progress), 1)
        self.assertEqual(progress[0].used, Decimal("800.00"))
        self.assertEqual(progress[0].remaining, Decimal("200.00"))
        self.assertEqual(progress[0].level, LEVEL_NORMAL)

    def test_已用达到九成标为接近上限(self) -> None:
        """验证 REQ-029：恰好达到预算九成时按触发处理，标为接近上限。"""
        self.ctx.budgets.set_budget(
            self.admin.user_id, self.ledger_id, None, Decimal("1000.00")
        )
        self.make_approved(self.writer, "900.00")
        progress = self.ctx.budgets.budget_progress(
            self.admin.user_id, self.ledger_id, "2026-11"
        )
        self.assertEqual(progress[0].used, Decimal("900.00"))
        self.assertEqual(progress[0].level, LEVEL_WARNING)
        self.assertEqual(progress[0].level, "接近上限")

    def test_已用超过全额标为已超支(self) -> None:
        """验证 REQ-029：已用金额超过预算全额时标为已超支且不阻断操作。"""
        self.ctx.budgets.set_budget(
            self.admin.user_id, self.ledger_id, None, Decimal("1000.00")
        )
        self.make_approved(self.writer, "1200.00")
        progress = self.ctx.budgets.budget_progress(
            self.admin.user_id, self.ledger_id, "2026-11"
        )
        self.assertEqual(progress[0].used, Decimal("1200.00"))
        self.assertEqual(progress[0].remaining, Decimal("-200.00"))
        self.assertEqual(progress[0].level, LEVEL_OVER)
        self.assertEqual(progress[0].level, "已超支")

    def test_分类预算只统计该分类的支出(self) -> None:
        """验证 REQ-028：分类预算的已用金额只统计该分类下的支出。"""
        food = self.category("餐饮")
        traffic = self.category("交通")
        self.ctx.budgets.set_budget(
            self.admin.user_id, self.ledger_id, food.category_id, Decimal("1000.00")
        )
        self.make_approved(self.writer, "300.00", category=food)
        self.make_approved(self.writer, "700.00", category=traffic)
        progress = self.ctx.budgets.budget_progress(
            self.admin.user_id, self.ledger_id, "2026-11"
        )
        self.assertEqual(len(progress), 1)
        self.assertEqual(progress[0].used, Decimal("300.00"))
        self.assertEqual(progress[0].level, LEVEL_NORMAL)

    def test_预算已用只统计已通过记录(self) -> None:
        """验证 REQ-024、REQ-029：预算已用金额沿用统计口径，只计已通过记录。"""
        self.ctx.budgets.set_budget(
            self.admin.user_id, self.ledger_id, None, Decimal("1000.00")
        )
        self.make_approved(self.writer, "500.00")
        self.create_draft(self.writer, self.draft_input("900.00"))
        progress = self.ctx.budgets.budget_progress(
            self.admin.user_id, self.ledger_id, "2026-11"
        )
        self.assertEqual(progress[0].used, Decimal("500.00"))

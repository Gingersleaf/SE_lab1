"""金额校验与分摊算法的单元测试（支撑层）。

对应支撑模块组件 ``AmountAllocator``，覆盖 REQ-017（金额取值与精度校验）、
REQ-018（单笔金额上限）、REQ-019（分摊明细的确定与余数归属）、
REQ-020（分摊金额与记录金额的一致性校验）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from shared_ledger.domain.errors import ValidationError
from shared_ledger.support.amount_allocator import AmountAllocator, Participant

from tests.base import ContextTestCase


class AmountValidationTest(ContextTestCase):
    """金额取值与精度的校验用例。"""

    def test_金额为零被拒绝(self) -> None:
        """验证 REQ-017：金额为零时校验不通过并提示必须大于零。"""
        with self.assertRaises(ValidationError) as ctx:
            AmountAllocator.validate_amount(Decimal("0"))
        self.assertIn("必须大于零", str(ctx.exception))

    def test_金额为负数被拒绝(self) -> None:
        """验证 REQ-017：金额为 -100 时校验不通过并提示必须大于零。"""
        with self.assertRaises(ValidationError) as ctx:
            AmountAllocator.validate_amount(Decimal("-100"))
        self.assertIn("必须大于零", str(ctx.exception))

    def test_金额超过两位小数被拒绝(self) -> None:
        """验证 REQ-017：金额 10.555 超过两位小数时校验不通过。"""
        with self.assertRaises(ValidationError) as ctx:
            AmountAllocator.validate_amount(Decimal("10.555"))
        self.assertIn("最多保留两位小数", str(ctx.exception))

    def test_金额恰好两位小数可以通过(self) -> None:
        """验证 REQ-017：金额 10.50 合法，且归一化后仍为两位小数。"""
        result = AmountAllocator.validate_amount(Decimal("10.50"))
        self.assertEqual(result, Decimal("10.50"))
        self.assertEqual(result.as_tuple().exponent, -2)

    def test_金额等于单笔上限可以通过(self) -> None:
        """验证 REQ-018：金额恰好等于 500000.00 元时视为合法。"""
        result = AmountAllocator.validate_amount(Decimal("500000.00"))
        self.assertEqual(result, AmountAllocator.MAX_RECORD_AMOUNT)

    def test_金额超过单笔上限被拒绝(self) -> None:
        """验证 REQ-018：金额 500000.01 元被拒绝，提示中含具体限额数值。"""
        with self.assertRaises(ValidationError) as ctx:
            AmountAllocator.validate_amount(Decimal("500000.01"))
        self.assertIn("超出单笔限额", str(ctx.exception))
        self.assertIn("500000.00", str(ctx.exception))

    def test_草稿阶段不校验单笔上限(self) -> None:
        """验证 REQ-018：草稿保存阶段不校验上限，提交阶段才校验。

        ``check_limit=False`` 用于草稿保存，允许超限金额先存草稿；
        正式提交时 ``check_limit=True`` 才会拒绝超限记录。
        """
        draft_amount = AmountAllocator.validate_amount(
            Decimal("500000.01"), check_limit=False
        )
        self.assertEqual(draft_amount, Decimal("500000.01"))
        with self.assertRaises(ValidationError):
            AmountAllocator.validate_amount(Decimal("500000.01"), check_limit=True)

    def test_单笔上限与精度常量取值正确(self) -> None:
        """验证 REQ-018：单笔上限常量为 500000.00 元，最多两位小数。"""
        self.assertEqual(AmountAllocator.MAX_RECORD_AMOUNT, Decimal("500000.00"))
        self.assertEqual(AmountAllocator.MAX_DECIMAL_PLACES, 2)


class SplitEvenlyTest(ContextTestCase):
    """均摊算法与分摊一致性校验的用例。"""

    @staticmethod
    def _participants() -> list:
        """构造三名加入时间依次递延的参与者。"""
        base = datetime(2026, 11, 1, 9, 0, 0)
        return [
            Participant(member_id="M2", joined_at=base + timedelta(minutes=2)),
            Participant(member_id="M1", joined_at=base),
            Participant(member_id="M3", joined_at=base + timedelta(minutes=1)),
        ]

    def test_均摊除不尽时余数归给加入最早者(self) -> None:
        """验证 REQ-019：10.00 元分给三人，余数 0.01 元归给加入账本最早者。"""
        allocations = AmountAllocator.split_evenly(Decimal("10.00"), self._participants())
        by_member = {item.member_id: item for item in allocations}
        self.assertEqual(by_member["M1"].amount, Decimal("3.34"))
        self.assertEqual(by_member["M2"].amount, Decimal("3.33"))
        self.assertEqual(by_member["M3"].amount, Decimal("3.33"))
        self.assertTrue(by_member["M1"].is_remainder_holder)
        self.assertFalse(by_member["M2"].is_remainder_holder)
        self.assertFalse(by_member["M3"].is_remainder_holder)
        self.assertEqual(
            AmountAllocator.is_remainder_holder(allocations), "M1"
        )

    def test_均摊结果之和等于总金额(self) -> None:
        """验证 REQ-020：各成员分摊金额之和必须精确等于记录金额。"""
        allocations = AmountAllocator.split_evenly(Decimal("100.00"), self._participants())
        total = sum((item.amount for item in allocations), Decimal("0.00"))
        self.assertEqual(total, Decimal("100.00"))

    def test_整除时没有余数归属者(self) -> None:
        """验证 REQ-019：金额可整除时不存在余数归属者。"""
        allocations = AmountAllocator.split_evenly(Decimal("99.00"), self._participants())
        for item in allocations:
            self.assertEqual(item.amount, Decimal("33.00"))
            self.assertFalse(item.is_remainder_holder)
        self.assertIsNone(AmountAllocator.is_remainder_holder(allocations))

    def test_参与分摊成员重复时被拒绝(self) -> None:
        """验证 REQ-019：参与分摊的成员中出现重复人员时保存被拒绝。"""
        base = datetime(2026, 11, 1, 9, 0, 0)
        participants = [
            Participant(member_id="M1", joined_at=base),
            Participant(member_id="M1", joined_at=base + timedelta(minutes=1)),
        ]
        with self.assertRaises(ValidationError) as ctx:
            AmountAllocator.split_evenly(Decimal("10.00"), participants)
        self.assertIn("重复人员", str(ctx.exception))

    def test_参与人数不足被拒绝(self) -> None:
        """验证 REQ-019：至少需要一名成员参与分摊。"""
        with self.assertRaises(ValidationError) as ctx:
            AmountAllocator.split_evenly(Decimal("10.00"), [])
        self.assertIn("至少需要一名成员参与分摊", str(ctx.exception))

    def test_分摊金额之和不符时被拒绝(self) -> None:
        """验证 REQ-020：分摊金额之和比记录金额少 0.01 元时校验不通过。"""
        with self.assertRaises(ValidationError) as ctx:
            AmountAllocator.validate_share_sum(
                Decimal("100.00"), [Decimal("50.00"), Decimal("49.99")]
            )
        self.assertIn("分摊金额之和与记录金额不符", str(ctx.exception))

    def test_分摊金额之和一致时通过(self) -> None:
        """验证 REQ-020：分摊金额之和等于记录金额时校验通过。"""
        AmountAllocator.validate_share_sum(
            Decimal("100.00"), [Decimal("50.00"), Decimal("50.00")]
        )

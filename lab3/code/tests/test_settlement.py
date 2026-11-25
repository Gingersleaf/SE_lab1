"""结算单生成、确认、申诉与裁决的单元测试。

覆盖 REQ-030（发起结算并生成结算单）、REQ-031（结算转账方案生成）、
REQ-032（结算单成员确认）、REQ-033（结算申诉与管理员裁决）与
REQ-034（结算单的数据快照隔离）。
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from shared_ledger.domain.enums import Role, RecordType, SettlementStatus
from shared_ledger.domain.errors import (
    BusinessRuleError,
    PermissionDeniedError,
    StateConflictError,
    ValidationError,
)

from tests.base import LedgerTestCase


class SettlementTestBase(LedgerTestCase):
    """结算用例的公共夹具：构造两名应付方与两名应收方。"""

    def setUp(self) -> None:
        """建立账本并铺好四个参与结算的成员。"""
        super().setUp()
        self.payer_a = self.ctx.auth.register("payer_a", "付款人甲", "123456")
        self.payer_b = self.ctx.auth.register("payer_b", "付款人乙", "123456")
        self.receiver_a = self.ctx.auth.register("receiver_a", "收款人甲", "123456")
        self.receiver_b = self.ctx.auth.register("receiver_b", "收款人乙", "123456")
        self.payer_a_member = self.join(self.payer_a, Role.WRITER)
        self.payer_b_member = self.join(self.payer_b, Role.WRITER)
        self.receiver_a_member = self.join(self.receiver_a, Role.WRITER)
        self.receiver_b_member = self.join(self.receiver_b, Role.WRITER)

    def make_settlement(self):
        """铺好已通过记录并生成一张结算单。

        成员净额为：付款人甲 -100.00、付款人乙 -40.00、
        收款人甲 +100.00、收款人乙 +40.00。
        """
        self.make_approved(
            self.payer_a,
            "100.00",
            payer_member_id=self.payer_a_member.member_id,
            participant_member_ids=[self.payer_a_member.member_id],
        )
        self.make_approved(
            self.payer_b,
            "40.00",
            payer_member_id=self.payer_b_member.member_id,
            participant_member_ids=[self.payer_b_member.member_id],
        )
        self.make_approved(
            self.receiver_a,
            "100.00",
            record_type=RecordType.INCOME,
            payer_member_id=self.receiver_a_member.member_id,
            participant_member_ids=[self.receiver_a_member.member_id],
        )
        self.make_approved(
            self.receiver_b,
            "40.00",
            record_type=RecordType.INCOME,
            payer_member_id=self.receiver_b_member.member_id,
            participant_member_ids=[self.receiver_b_member.member_id],
        )
        return self.ctx.settlements.create_settlement(
            self.admin.user_id, self.ledger_id
        )

    def _make_unaligned_settlement(self):
        """构造净额无法两两对齐的结算单。

        成员净额为：付款人甲 -100.00、付款人乙 -40.00、
        收款人甲 +50.00、收款人乙 +90.00。
        """
        self.make_approved(
            self.payer_a,
            "100.00",
            payer_member_id=self.payer_a_member.member_id,
            participant_member_ids=[self.payer_a_member.member_id],
        )
        self.make_approved(
            self.payer_b,
            "40.00",
            payer_member_id=self.payer_b_member.member_id,
            participant_member_ids=[self.payer_b_member.member_id],
        )
        self.make_approved(
            self.receiver_a,
            "50.00",
            record_type=RecordType.INCOME,
            payer_member_id=self.receiver_a_member.member_id,
            participant_member_ids=[self.receiver_a_member.member_id],
        )
        self.make_approved(
            self.receiver_b,
            "90.00",
            record_type=RecordType.INCOME,
            payer_member_id=self.receiver_b_member.member_id,
            participant_member_ids=[self.receiver_b_member.member_id],
        )
        return self.ctx.settlements.create_settlement(
            self.admin.user_id, self.ledger_id
        )


class CreateSettlementTest(SettlementTestBase):
    """发起结算的用例。"""

    def test_无可结算记录时发起结算被拒绝(self) -> None:
        """验证 REQ-030：账本内没有可参与结算的记录时不生成结算单。"""
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.settlements.create_settlement(self.admin.user_id, self.ledger_id)
        self.assertIn("没有可参与结算的记录", str(ctx.exception))
        self.assertEqual(
            len(self.ctx.settlements.list_settlements(self.admin.user_id, self.ledger_id)), 0
        )

    def test_结算单初始状态为待确认且成员净额之和等于账本净额(self) -> None:
        """验证 REQ-030：结算单状态为待确认，成员净额之和与账本净额一致。"""
        settlement = self.make_settlement()
        self.assertEqual(settlement.settlement.status, SettlementStatus.PENDING_CONFIRM)
        self.assertEqual(settlement.total_members, 4)
        total = sum((item.net_amount for item in settlement.members), Decimal("0.00"))
        self.assertEqual(total, settlement.ledger_net)
        self.assertEqual(total, Decimal("0.00"))

    def test_非管理员发起结算被拒绝(self) -> None:
        """验证 REQ-030、REQ-044：非管理员发起结算被拒绝。"""
        self.make_approved(self.writer, "50.00")
        with self.assertRaises(PermissionDeniedError):
            self.ctx.settlements.create_settlement(self.writer.user_id, self.ledger_id)


class TransferPlanTest(SettlementTestBase):
    """转账方案生成的用例。"""

    def test_转账条目金额之和等于应付方净额之和(self) -> None:
        """验证 REQ-031：各条目金额之和等于应付方净额之和。"""
        settlement = self.make_settlement()
        payer_total = sum(
            (-item.net_amount for item in settlement.members if item.net_amount < 0),
            Decimal("0.00"),
        )
        plan_total = sum((item.amount for item in settlement.plan), Decimal("0.00"))
        self.assertEqual(plan_total, payer_total)
        self.assertEqual(plan_total, Decimal("140.00"))

    def test_每条转账的转出方金额大于零(self) -> None:
        """验证 REQ-031：每一条转账条目的金额均大于零。"""
        settlement = self.make_settlement()
        self.assertTrue(settlement.plan)
        for item in settlement.plan:
            self.assertGreater(item.amount, Decimal("0.00"))
            self.assertNotEqual(item.from_member_id, item.to_member_id)

    def test_转账条目数不超过应收方与应付方人数中较小的一方(self) -> None:
        """验证 REQ-031：条目数不多于应收方人数与应付方人数中较小的一方。"""
        settlement = self.make_settlement()
        payers = [item for item in settlement.members if item.net_amount < 0]
        receivers = [item for item in settlement.members if item.net_amount > 0]
        self.assertLessEqual(
            len(settlement.plan), min(len(payers), len(receivers))
        )
        self.assertEqual(len(settlement.plan), 2)

    def test_转账方案的应付方与应收方划分正确(self) -> None:
        """验证 REQ-031：转账条目的转出方均为应付方，转入方均为应收方。"""
        settlement = self.make_settlement()
        payers = {item.member_id for item in settlement.members if item.net_amount < 0}
        receivers = {item.member_id for item in settlement.members if item.net_amount > 0}
        for item in settlement.plan:
            self.assertIn(item.from_member_id, payers)
            self.assertIn(item.to_member_id, receivers)

    @unittest.expectedFailure
    def test_净额不对齐时转账条目数仍不超过较小一方(self) -> None:
        """验证 REQ-031 验收方法：条目数不多于应收方与应付方人数中较小的一方。

        本用例按需求原文断言，当前实现**无法**满足，原因不在实现而在需求：

        验收方法要求「条目数不多于应收方人数与应付方人数中较小的一方」。
        以本用例构造的数据为例——应付方 −100.00、−40.00，应收方 +50.00、+90.00，
        双方各 2 人，上限为 2 条。但若只用 2 条转账，每位付款人只能付给一位
        收款人：付款 100.00 的人必须整笔付给某一位收款人，而两位收款人分别
        只应收 50.00 与 90.00，都收不下 100.00，因此 2 条方案在数学上不存在。
        最小方案是 3 条（如「付款 100 的人先付给应收 90 的人 90 元，
        再付给应收 50 的人 10 元，付款 40 的人付给应收 50 的人 40 元」）。

        REQ-031 的「正常结果」同时写明「条目数按金额排序后依次配对生成，
        不设硬性条数上限」，两条表述本身存在张力。实现遵循「正常结果」：
        先配对剩余金额完全相等的两方以尽量减少条目，再按金额从大到小贪心配对。
        本用例保留为预期失败，作为该需求张力的证据。
        """
        settlement = self._make_unaligned_settlement()
        payers = [item for item in settlement.members if item.net_amount < 0]
        receivers = [item for item in settlement.members if item.net_amount > 0]
        self.assertLessEqual(len(settlement.plan), min(len(payers), len(receivers)))


class ConfirmSettlementTest(SettlementTestBase):
    """结算单成员确认的用例。"""

    def test_成员逐个确认后状态变为已确认(self) -> None:
        """验证 REQ-032：全部参与成员确认完毕后结算单状态变为已确认。"""
        settlement = self.make_settlement()
        settlement_id = settlement.settlement.settlement_id
        users = [
            self.payer_a,
            self.payer_b,
            self.receiver_a,
            self.receiver_b,
        ]
        detail = None
        for index, user in enumerate(users):
            detail = self.ctx.settlements.confirm(
                user.user_id, self.ledger_id, settlement_id
            )
            self.assertEqual(detail.confirmed_count, index + 1)
            if index < len(users) - 1:
                self.assertEqual(
                    detail.settlement.status, SettlementStatus.PENDING_CONFIRM
                )
        self.assertEqual(detail.settlement.status, SettlementStatus.CONFIRMED)
        self.assertTrue(detail.all_confirmed)

    def test_重复确认幂等不产生重复记录(self) -> None:
        """验证 REQ-032：对已确认的成员重复确认按幂等处理，不产生重复记录。"""
        settlement = self.make_settlement()
        settlement_id = settlement.settlement.settlement_id
        first = self.ctx.settlements.confirm(
            self.payer_a.user_id, self.ledger_id, settlement_id
        )
        second = self.ctx.settlements.confirm(
            self.payer_a.user_id, self.ledger_id, settlement_id
        )
        self.assertEqual(second.confirmed_count, first.confirmed_count)
        rows = self.ctx.repos.settlement_members.list_by_settlement(settlement_id)
        self.assertEqual(len(rows), 4)
        self.assertEqual(len([item for item in rows if item.confirmed]), 1)
        confirm_logs = [
            item
            for item in self.ctx.repos.logs.list_by_ledger(self.ledger_id)
            if item.action.value == "SETTLEMENT_CONFIRM"
        ]
        self.assertEqual(len(confirm_logs), 1)

    def test_非参与成员确认被拒绝(self) -> None:
        """验证 REQ-032：非参与成员确认结算单被拒绝。"""
        settlement = self.make_settlement()
        with self.assertRaises(PermissionDeniedError):
            self.ctx.settlements.confirm(
                self.reader.user_id, self.ledger_id, settlement.settlement.settlement_id
            )


class AppealAndVerdictTest(SettlementTestBase):
    """结算申诉与管理员裁决的用例。"""

    def test_申诉后状态为有争议(self) -> None:
        """验证 REQ-033：成员发起申诉后结算单状态变为有争议。"""
        settlement = self.make_settlement()
        appealed = self.ctx.settlements.appeal(
            self.payer_a.user_id,
            self.ledger_id,
            settlement.settlement.settlement_id,
            "10 月的餐饮分摊金额与我记的不一致",
        )
        self.assertEqual(appealed.settlement.status, SettlementStatus.DISPUTED)
        row = self.ctx.repos.settlement_members.find(
            settlement.settlement.settlement_id, self.payer_a_member.member_id
        )
        self.assertTrue(row.appealed)
        self.assertEqual(row.appeal_reason, "10 月的餐饮分摊金额与我记的不一致")

    def test_申诉必须填写原因(self) -> None:
        """验证 REQ-033：未填写申诉原因时申诉被拒绝。"""
        settlement = self.make_settlement()
        with self.assertRaises(ValidationError):
            self.ctx.settlements.appeal(
                self.payer_a.user_id,
                self.ledger_id,
                settlement.settlement.settlement_id,
                "  ",
            )

    def test_裁决维持后状态为已确认且无需重新确认(self) -> None:
        """验证 REQ-033：管理员裁决为维持后结算单变为已确认，不要求成员重新确认。"""
        settlement = self.make_settlement()
        settlement_id = settlement.settlement.settlement_id
        self.ctx.settlements.appeal(
            self.payer_a.user_id, self.ledger_id, settlement_id, "金额有疑问"
        )
        verdict = self.ctx.settlements.verdict(
            self.admin.user_id, self.ledger_id, settlement_id, "维持", "核对分摊明细后确认无误"
        )
        self.assertEqual(verdict.settlement.status, SettlementStatus.CONFIRMED)
        self.assertEqual(verdict.settlement.verdict, "维持")
        self.assertEqual(verdict.settlement.verdict_reason, "核对分摊明细后确认无误")

    def test_裁决作废后状态为已作废(self) -> None:
        """验证 REQ-033：管理员裁决为作废后结算单变为已作废。"""
        settlement = self.make_settlement()
        settlement_id = settlement.settlement.settlement_id
        self.ctx.settlements.appeal(
            self.payer_a.user_id, self.ledger_id, settlement_id, "金额有疑问"
        )
        verdict = self.ctx.settlements.verdict(
            self.admin.user_id, self.ledger_id, settlement_id, "作废", "分摊明细有误，作废本单"
        )
        self.assertEqual(verdict.settlement.status, SettlementStatus.VOIDED)
        self.assertEqual(verdict.settlement.verdict, "作废")

    def test_已确认的结算单不能再申诉与裁决(self) -> None:
        """验证 REQ-033：已确认的结算单不能再发起申诉与裁决。"""
        settlement = self.make_settlement()
        settlement_id = settlement.settlement.settlement_id
        for user in (self.payer_a, self.payer_b, self.receiver_a, self.receiver_b):
            self.ctx.settlements.confirm(user.user_id, self.ledger_id, settlement_id)
        with self.assertRaises(StateConflictError):
            self.ctx.settlements.appeal(
                self.payer_a.user_id, self.ledger_id, settlement_id, "还有异议"
            )
        with self.assertRaises(StateConflictError):
            self.ctx.settlements.verdict(
                self.admin.user_id, self.ledger_id, settlement_id, "维持", "重复裁决"
            )

    def test_已作废的结算单不能再申诉与裁决(self) -> None:
        """验证 REQ-034：已作废的结算单不可恢复，也不能再申诉与裁决。"""
        settlement = self.make_settlement()
        settlement_id = settlement.settlement.settlement_id
        self.ctx.settlements.appeal(
            self.payer_a.user_id, self.ledger_id, settlement_id, "金额有疑问"
        )
        self.ctx.settlements.verdict(
            self.admin.user_id, self.ledger_id, settlement_id, "作废", "作废本单"
        )
        with self.assertRaises(StateConflictError):
            self.ctx.settlements.appeal(
                self.payer_a.user_id, self.ledger_id, settlement_id, "还有异议"
            )
        with self.assertRaises(StateConflictError):
            self.ctx.settlements.verdict(
                self.admin.user_id, self.ledger_id, settlement_id, "维持", "重复裁决"
            )

    def test_非管理员裁决被拒绝(self) -> None:
        """验证 REQ-033、REQ-044：非管理员执行裁决被拒绝。"""
        settlement = self.make_settlement()
        settlement_id = settlement.settlement.settlement_id
        self.ctx.settlements.appeal(
            self.payer_a.user_id, self.ledger_id, settlement_id, "金额有疑问"
        )
        with self.assertRaises(PermissionDeniedError):
            self.ctx.settlements.verdict(
                self.writer.user_id, self.ledger_id, settlement_id, "维持", "自行裁决"
            )


class SettlementSnapshotTest(SettlementTestBase):
    """结算单快照隔离的用例。"""

    def test_结算后新增记录原结算单内容不变(self) -> None:
        """验证 REQ-034：结算单生成后新增记录不追溯修改已生成的结算单。"""
        settlement = self.make_settlement()
        settlement_id = settlement.settlement.settlement_id
        before_members = {
            item.member_id: item.net_amount for item in settlement.members
        }
        before_plan = [(item.from_member_id, item.to_member_id, item.amount) for item in settlement.plan]
        before_records = list(settlement.settlement.snapshot_record_ids)

        self.make_approved(
            self.payer_a,
            "60.00",
            payer_member_id=self.payer_a_member.member_id,
            participant_member_ids=[self.payer_a_member.member_id],
        )

        after = self.ctx.settlements.get_settlement(
            self.admin.user_id, self.ledger_id, settlement_id
        )
        after_members = {item.member_id: item.net_amount for item in after.members}
        after_plan = [
            (item.from_member_id, item.to_member_id, item.amount) for item in after.plan
        ]
        self.assertEqual(after_members, before_members)
        self.assertEqual(after_plan, before_plan)
        self.assertEqual(list(after.settlement.snapshot_record_ids), before_records)

    def test_新增记录计入下一次结算(self) -> None:
        """验证 REQ-034：结算后新增的记录在第二次结算时被正确纳入。"""
        first = self.make_settlement()
        first_ids = set(first.settlement.snapshot_record_ids)
        self.make_approved(
            self.payer_a,
            "60.00",
            payer_member_id=self.payer_a_member.member_id,
            participant_member_ids=[self.payer_a_member.member_id],
        )
        second = self.ctx.settlements.create_settlement(
            self.admin.user_id, self.ledger_id
        )
        second_ids = set(second.settlement.snapshot_record_ids)
        self.assertTrue(second_ids > first_ids)
        payer_a_row = next(
            item for item in second.members if item.member_id == self.payer_a_member.member_id
        )
        self.assertEqual(payer_a_row.net_amount, Decimal("-160.00"))

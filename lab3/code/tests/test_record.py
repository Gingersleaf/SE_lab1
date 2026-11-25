"""收支记录录入、提交与审核的单元测试。

覆盖 REQ-007（录入收支记录并保存草稿）、REQ-008（提交记录进入审核）、
REQ-009（审核通过）、REQ-010（审核驳回）、REQ-011（记录人撤回待审核记录）、
REQ-012（管理员作废记录）、REQ-013（已通过记录的冲正更正）、
REQ-015（状态流转规则）、REQ-016（管理员自审豁免）、
REQ-017、REQ-018、REQ-019、REQ-038 与 REQ-044。
"""

from __future__ import annotations

from decimal import Decimal

from shared_ledger.domain.enums import LogActionType, RecordStatus
from shared_ledger.domain.errors import (
    BusinessRuleError,
    PermissionDeniedError,
    StateConflictError,
    ValidationError,
)

from tests.base import LedgerTestCase


class RecordLifecycleTest(LedgerTestCase):
    """记录从草稿到已通过的完整流转用例。"""

    def test_草稿保存后状态为草稿且分摊之和等于金额(self) -> None:
        """验证 REQ-007、REQ-019、REQ-020：草稿保存成功且分摊明细之和等于金额。"""
        record = self.create_draft(
            self.writer,
            self.draft_input(
                "90.00",
                payer_member_id=self.writer_member.member_id,
                participant_member_ids=[
                    self.writer_member.member_id,
                    self.admin_member.member_id,
                ],
            ),
        )
        self.assertEqual(record.status, RecordStatus.DRAFT)
        self.assertEqual(record.amount, Decimal("90.00"))
        self.assertEqual(record.version, 1)
        shares = self.ctx.repos.shares.list_by_record(record.record_id)
        self.assertEqual(len(shares), 2)
        total = sum((item.amount for item in shares), Decimal("0.00"))
        self.assertEqual(total, Decimal("90.00"))

    def test_提交审核后进入待审核并出现在管理员待审核列表(self) -> None:
        """验证 REQ-008：提交后状态变为待审核并出现在管理员的待审核列表中。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        submitted = self.submit(self.writer, record)
        self.assertEqual(submitted.status, RecordStatus.PENDING)
        self.assertIsNotNone(submitted.submitted_at)
        pending = self.ctx.audits.list_pending(self.admin.user_id, self.ledger_id)
        self.assertTrue(any(item.record_id == record.record_id for item in pending))
        drafts = self.ctx.records.list_drafts(self.writer.user_id, self.ledger_id)
        self.assertFalse(any(item.record_id == record.record_id for item in drafts))

    def test_审核通过后状态为已通过并计入统计(self) -> None:
        """验证 REQ-009、REQ-024：审核通过后记录立即计入统计。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, record)
        approved = self.approve(record)
        self.assertEqual(approved.status, RecordStatus.APPROVED)
        self.assertIsNotNone(approved.reviewed_at)
        self.assertEqual(approved.reviewer_id, self.admin_member.member_id)
        overview = self.ctx.statistics.overview(self.admin.user_id, self.ledger_id, "2026-11")
        self.assertEqual(overview.expense, Decimal("100.00"))

    def test_驳回必须填写原因(self) -> None:
        """验证 REQ-010：驳回未填写原因时不允许提交驳回操作。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, record)
        with self.assertRaises(ValidationError) as ctx:
            self.ctx.audits.reject(self.admin.user_id, self.ledger_id, record.record_id, "   ")
        self.assertIn("必须填写驳回原因", str(ctx.exception))
        stored = self.ctx.repos.records.find_by_id(record.record_id)
        self.assertEqual(stored.status, RecordStatus.PENDING)

    def test_驳回后记录人可修改并重新提交(self) -> None:
        """验证 REQ-010：驳回原因保留在历史中，记录人修改后可重新提交。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, record)
        rejected = self.ctx.audits.reject(
            self.admin.user_id, self.ledger_id, record.record_id, "金额需复核"
        )
        self.assertEqual(rejected.status, RecordStatus.REJECTED)
        detail = self.ctx.records.get_detail(
            self.writer.user_id, self.ledger_id, record.record_id
        )
        reasons = [item.reason for item in detail.traces]
        self.assertIn("金额需复核", reasons)

        updated = self.ctx.records.update_draft(
            self.writer.user_id,
            self.ledger_id,
            record.record_id,
            self.draft_input("120.00"),
            expected_version=rejected.version,
        )
        self.assertEqual(updated.status, RecordStatus.DRAFT)
        self.assertEqual(updated.amount, Decimal("120.00"))
        resubmitted = self.submit(self.writer, updated)
        self.assertEqual(resubmitted.status, RecordStatus.PENDING)

    def test_记录人可撤回待审核记录(self) -> None:
        """验证 REQ-011：记录人撤回后状态回到草稿并重新出现在草稿列表。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, record)
        withdrawn = self.ctx.records.withdraw(
            self.writer.user_id, self.ledger_id, record.record_id
        )
        self.assertEqual(withdrawn.status, RecordStatus.DRAFT)
        self.assertIsNone(withdrawn.submitted_at)
        drafts = self.ctx.records.list_drafts(self.writer.user_id, self.ledger_id)
        self.assertTrue(any(item.record_id == record.record_id for item in drafts))

    def test_非录入人撤回被拒绝(self) -> None:
        """验证 REQ-011：非记录人发起撤回被拒绝并留下越权日志。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, record)
        with self.assertRaises(PermissionDeniedError):
            self.ctx.records.withdraw(
                self.admin.user_id, self.ledger_id, record.record_id
            )
        denials = [
            item
            for item in self.ctx.repos.logs.list_by_ledger(self.ledger_id)
            if item.action is LogActionType.ACCESS_DENIED
        ]
        self.assertEqual(len(denials), 1)

    def test_已通过记录撤回被拒绝(self) -> None:
        """验证 REQ-036：记录已被审核通过后撤回请求被拒绝并提示状态已变更。"""
        record = self.make_approved(self.writer, "100.00")
        with self.assertRaises(StateConflictError) as ctx:
            self.ctx.records.withdraw(
                self.writer.user_id, self.ledger_id, record.record_id
            )
        self.assertIn("状态已变更", str(ctx.exception))

    def test_作废必须填写原因(self) -> None:
        """验证 REQ-012：作废未填写原因时不允许提交作废操作。"""
        record = self.make_approved(self.writer, "100.00")
        with self.assertRaises(ValidationError) as ctx:
            self.ctx.audits.void_record(
                self.admin.user_id, self.ledger_id, record.record_id, ""
            )
        self.assertIn("必须填写作废原因", str(ctx.exception))
        stored = self.ctx.repos.records.find_by_id(record.record_id)
        self.assertEqual(stored.status, RecordStatus.APPROVED)

    def test_已作废记录是终态且不计入统计(self) -> None:
        """验证 REQ-012、REQ-015：已作废记录不可再次作废，也不计入统计。"""
        record = self.make_approved(self.writer, "100.00")
        voided = self.ctx.audits.void_record(
            self.admin.user_id, self.ledger_id, record.record_id, "录入有误"
        )
        self.assertEqual(voided.status, RecordStatus.VOIDED)
        with self.assertRaises(StateConflictError) as ctx:
            self.ctx.audits.void_record(
                self.admin.user_id, self.ledger_id, record.record_id, "再次作废"
            )
        self.assertIn("记录状态已变更", str(ctx.exception))
        stored = self.ctx.repos.records.find_by_id(record.record_id)
        self.assertEqual(stored.status, RecordStatus.VOIDED)
        overview = self.ctx.statistics.overview(self.admin.user_id, self.ledger_id, "2026-11")
        self.assertEqual(overview.expense, Decimal("0.00"))


class RecordPermissionTest(LedgerTestCase):
    """记录录入权限的用例。"""

    def test_只读成员不能录入记录(self) -> None:
        """验证 REQ-044：只读成员不能录入任何记录。"""
        with self.assertRaises(PermissionDeniedError):
            self.create_draft(
                self.reader,
                self.draft_input(
                    "30.00",
                    payer_member_id=self.reader_member.member_id,
                    participant_member_ids=[self.reader_member.member_id],
                ),
            )

    def test_只读成员不能作为付款人(self) -> None:
        """验证 REQ-019：只读成员不能作为记录付款人。"""
        payload = self.draft_input(
            "30.00",
            payer_member_id=self.reader_member.member_id,
            participant_member_ids=[self.writer_member.member_id],
        )
        with self.assertRaises(BusinessRuleError) as ctx:
            self.create_draft(self.writer, payload)
        self.assertIn("只读成员不能作为付款人或参与分摊", str(ctx.exception))

    def test_只读成员不能参与分摊(self) -> None:
        """验证 REQ-019：只读成员不能作为分摊参与者。"""
        payload = self.draft_input(
            "30.00",
            payer_member_id=self.writer_member.member_id,
            participant_member_ids=[
                self.writer_member.member_id,
                self.reader_member.member_id,
            ],
        )
        with self.assertRaises(BusinessRuleError) as ctx:
            self.create_draft(self.writer, payload)
        self.assertIn("只读成员不能作为付款人或参与分摊", str(ctx.exception))

    def test_分摊成员重复时被拒绝(self) -> None:
        """验证 REQ-019：参与分摊成员中出现重复人员时保存被拒绝。"""
        payload = self.draft_input(
            "30.00",
            payer_member_id=self.writer_member.member_id,
            participant_member_ids=[
                self.writer_member.member_id,
                self.writer_member.member_id,
            ],
        )
        with self.assertRaises(BusinessRuleError) as ctx:
            self.create_draft(self.writer, payload)
        self.assertIn("重复人员", str(ctx.exception))

    def test_非管理员审核被拒绝(self) -> None:
        """验证 REQ-009、REQ-044：非管理员执行审核通过被拒绝。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, record)
        with self.assertRaises(PermissionDeniedError):
            self.ctx.audits.approve(self.writer.user_id, self.ledger_id, record.record_id)


class AmountRuleTest(LedgerTestCase):
    """记录金额规则的用例。"""

    def test_金额为零被拒绝(self) -> None:
        """验证 REQ-017：金额为零的记录不允许保存。"""
        with self.assertRaises(ValidationError) as ctx:
            self.create_draft(self.writer, self.draft_input("0"))
        self.assertIn("必须大于零", str(ctx.exception))

    def test_金额超过两位小数被拒绝(self) -> None:
        """验证 REQ-017：金额 10.555 元超过两位小数时不允许保存。"""
        with self.assertRaises(ValidationError) as ctx:
            self.create_draft(self.writer, self.draft_input("10.555"))
        self.assertIn("最多保留两位小数", str(ctx.exception))

    def test_草稿可保存超限金额但提交时被拒绝(self) -> None:
        """验证 REQ-018：超限金额允许以草稿保存但不允许提交。"""
        record = self.create_draft(self.writer, self.draft_input("500000.01"))
        self.assertEqual(record.status, RecordStatus.DRAFT)
        self.assertEqual(record.amount, Decimal("500000.01"))
        with self.assertRaises(ValidationError) as ctx:
            self.submit(self.writer, record)
        self.assertIn("超出单笔限额", str(ctx.exception))
        stored = self.ctx.repos.records.find_by_id(record.record_id)
        self.assertEqual(stored.status, RecordStatus.DRAFT)

    def test_金额等于单笔上限可以提交(self) -> None:
        """验证 REQ-018：金额恰好等于 500000.00 元时可以提交。"""
        record = self.create_draft(self.writer, self.draft_input("500000.00"))
        submitted = self.submit(self.writer, record)
        self.assertEqual(submitted.status, RecordStatus.PENDING)


class SelfReviewTest(LedgerTestCase):
    """管理员自审豁免的用例。"""

    def test_管理员提交本人录入的记录直接已通过(self) -> None:
        """验证 REQ-016：管理员本人录入的记录提交后直接置为已通过。"""
        record = self.create_draft(
            self.admin,
            self.draft_input(
                "200.00",
                payer_member_id=self.admin_member.member_id,
                participant_member_ids=[self.admin_member.member_id],
            ),
        )
        submitted = self.submit(self.admin, record)
        self.assertEqual(submitted.status, RecordStatus.APPROVED)
        overview = self.ctx.statistics.overview(self.admin.user_id, self.ledger_id, "2026-11")
        self.assertEqual(overview.expense, Decimal("200.00"))

    def test_管理员自审豁免写入自审日志(self) -> None:
        """验证 REQ-016、REQ-039：自审豁免行为完整记入操作日志。"""
        record = self.create_draft(
            self.admin,
            self.draft_input(
                "200.00",
                payer_member_id=self.admin_member.member_id,
                participant_member_ids=[self.admin_member.member_id],
            ),
        )
        self.submit(self.admin, record)
        self.assertIn(LogActionType.SELF_REVIEW.value, self.log_actions())

    def test_管理员操作他人录入的记录不构成自审豁免(self) -> None:
        """验证 REQ-016：管理员操作他人录入的记录仍进入待审核。"""
        record = self.create_draft(self.writer, self.draft_input("200.00"))
        submitted = self.submit(self.writer, record)
        self.assertEqual(submitted.status, RecordStatus.PENDING)


class ReversalTest(LedgerTestCase):
    """冲正更正的用例。"""

    def _make_pair(self) -> tuple:
        """构造一条已通过记录及其冲正记录（冲正记录仍为草稿）。"""
        original = self.make_approved(
            self.writer,
            "288.00",
            payer_member_id=self.writer_member.member_id,
            participant_member_ids=[
                self.writer_member.member_id,
                self.admin_member.member_id,
            ],
        )
        reversal = self.ctx.records.create_reversal(
            self.writer.user_id, self.ledger_id, original.record_id
        )
        return original, reversal

    def test_发起冲正后生成待审核的冲正记录(self) -> None:
        """验证 REQ-013：冲正记录按新记录流程进入草稿并关联原记录。"""
        original, reversal = self._make_pair()
        self.assertEqual(reversal.status, RecordStatus.DRAFT)
        self.assertEqual(reversal.reversal_of_id, original.record_id)
        self.assertEqual(reversal.amount, original.amount)
        self.assertEqual(reversal.record_date, original.record_date)
        stored = self.ctx.repos.records.find_by_id(original.record_id)
        self.assertEqual(stored.status, RecordStatus.APPROVED)

    def test_冲正记录审核通过后原记录变已冲正且双向关联(self) -> None:
        """验证 REQ-013：冲正生效后原记录状态为已冲正，两条记录双向关联。"""
        original, reversal = self._make_pair()
        self.submit(self.writer, reversal)
        self.approve(reversal)
        stored = self.ctx.repos.records.find_by_id(original.record_id)
        self.assertEqual(stored.status, RecordStatus.REVERSED)
        self.assertEqual(stored.reversed_by_id, reversal.record_id)
        self.assertEqual(reversal.reversal_of_id, original.record_id)

    def test_已冲正记录不能再次发起冲正(self) -> None:
        """验证 REQ-013：已冲正的记录不可再次发起冲正。"""
        original, reversal = self._make_pair()
        self.submit(self.writer, reversal)
        self.approve(reversal)
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.records.create_reversal(
                self.writer.user_id, self.ledger_id, original.record_id
            )
        self.assertIn("只有已通过的记录可以发起冲正", str(ctx.exception))

    def test_同一原记录不能同时存在两条待审核冲正记录(self) -> None:
        """验证 REQ-013：同一原记录同时只能存在一条待审核的冲正记录。"""
        original, _ = self._make_pair()
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.records.create_reversal(
                self.admin.user_id, self.ledger_id, original.record_id
            )
        self.assertIn("已有待审核的冲正记录", str(ctx.exception))

    def test_非本人录入也不能由他人发起冲正(self) -> None:
        """验证 REQ-013：非录入人且非管理员的成员不能发起冲正。"""
        original = self.make_approved(self.writer, "288.00")
        with self.assertRaises(PermissionDeniedError):
            self.ctx.records.create_reversal(
                self.reader.user_id, self.ledger_id, original.record_id
            )


class SubmitAfterLeaveTest(LedgerTestCase):
    """成员退出账本后提交记录的用例。"""

    def test_成员退出账本后提交被拒绝并提示已退出(self) -> None:
        """验证 REQ-038：提交审核时操作者已退出账本则提交失败并提示成员已退出账本。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.ctx.members.leave_ledger(self.writer.user_id, self.ledger_id)
        with self.assertRaises(PermissionDeniedError) as ctx:
            self.submit(self.writer, record)
        self.assertIn("成员已退出账本", str(ctx.exception))
        stored = self.ctx.repos.records.find_by_id(record.record_id)
        self.assertEqual(stored.status, RecordStatus.DRAFT)

    def test_提交后才退出的记录继续走审核流程(self) -> None:
        """验证 REQ-038：提交动作先完成时，记录按已提交状态继续走审核流程。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, record)
        self.ctx.members.leave_ledger(self.writer.user_id, self.ledger_id)
        approved = self.approve(record)
        self.assertEqual(approved.status, RecordStatus.APPROVED)

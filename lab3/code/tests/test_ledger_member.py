"""账本与成员管理的单元测试。

覆盖 REQ-001（创建账本并确定管理员）、REQ-004（调整成员角色）、
REQ-005（成员退出或被移除后的账本数据处理）、
REQ-006（退出成员重新加入后的结算资格）与 REQ-044（最小权限原则）。
"""

from __future__ import annotations

from decimal import Decimal

from shared_ledger.domain.entities import DEFAULT_CATEGORY_NAMES
from shared_ledger.domain.enums import LogActionType, MemberStatus, Role
from shared_ledger.domain.errors import BusinessRuleError, PermissionDeniedError

from tests.base import LedgerTestCase


class CreateLedgerTest(LedgerTestCase):
    """创建账本的用例。"""

    def test_创建账本后创建者是唯一管理员(self) -> None:
        """验证 REQ-001：账本创建者自动成为该账本的管理员。"""
        member = self.member_of(self.admin)
        self.assertEqual(member.role, Role.ADMIN)
        self.assertEqual(member.status, MemberStatus.ACTIVE)
        self.assertTrue(member.settlement_eligible)
        self.assertEqual(self.ledger.admin_member_id, member.member_id)

    def test_新账本自动带五个默认分类(self) -> None:
        """验证 REQ-001、REQ-021：新账本内自动铺好系统默认分类。"""
        categories = self.ctx.categories.list_categories(
            self.admin.user_id, self.ledger_id
        )
        self.assertEqual(len(categories), 5)
        self.assertEqual(
            tuple(item.name for item in categories), DEFAULT_CATEGORY_NAMES
        )
        for item in categories:
            self.assertTrue(item.is_default)
            self.assertEqual(item.status.value, "ENABLED")

    def test_创建账本会写入成员加入日志(self) -> None:
        """验证 REQ-039：创建账本这一关键操作留有日志。"""
        self.assertIn(LogActionType.MEMBER_JOIN.value, self.log_actions())


class ChangeRoleTest(LedgerTestCase):
    """成员角色调整的用例。"""

    def test_管理员不能被降级(self) -> None:
        """验证 REQ-046：管理员角色不可转让，不能把管理员降为记账成员。"""
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.members.change_role(
                self.admin.user_id,
                self.ledger_id,
                self.admin.user_id,
                Role.WRITER,
            )
        self.assertIn("管理员角色不可转让", str(ctx.exception))
        self.assertEqual(self.member_of(self.admin).role, Role.ADMIN)

    def test_不支持把成员提升为管理员(self) -> None:
        """验证 REQ-046：不能通过改角色新增管理员。"""
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.members.change_role(
                self.admin.user_id,
                self.ledger_id,
                self.writer.user_id,
                Role.ADMIN,
            )
        self.assertIn("不支持新增管理员", str(ctx.exception))
        self.assertEqual(self.member_of(self.writer).role, Role.WRITER)

    def test_只读成员提升为记账成员后立即可录入(self) -> None:
        """验证 REQ-004：角色调整立即生效，目标成员可立刻录入记录。"""
        updated = self.ctx.members.change_role(
            self.admin.user_id, self.ledger_id, self.reader.user_id, Role.WRITER
        )
        self.assertEqual(updated.role, Role.WRITER)
        self.assertTrue(updated.settlement_eligible)
        record = self.create_draft(
            self.reader, self.draft_input("30.00", payer_member_id=updated.member_id,
                                          participant_member_ids=[updated.member_id])
        )
        self.assertEqual(record.status.value, "DRAFT")

    def test_非管理员调整角色被拒绝并留下越权日志(self) -> None:
        """验证 REQ-004、REQ-044：非管理员调整角色被拒绝并记录越权日志。"""
        with self.assertRaises(PermissionDeniedError):
            self.ctx.members.change_role(
                self.writer.user_id, self.ledger_id, self.reader.user_id, Role.WRITER
            )
        denials = [
            item
            for item in self.ctx.repos.logs.list_by_ledger(self.ledger_id)
            if item.action is LogActionType.ACCESS_DENIED
        ]
        self.assertEqual(len(denials), 1)


class InviteMemberTest(LedgerTestCase):
    """邀请成员的用例。"""

    def test_非管理员邀请成员被拒绝并写入越权日志(self) -> None:
        """验证 REQ-002、REQ-044：非管理员邀请被拒绝并留下越权日志。"""
        with self.assertRaises(PermissionDeniedError):
            self.ctx.invitations.create_invitation(
                self.writer.user_id, self.ledger_id, Role.WRITER
            )
        denials = [
            item
            for item in self.ctx.repos.logs.list_by_ledger(self.ledger_id)
            if item.action is LogActionType.ACCESS_DENIED
        ]
        self.assertEqual(len(denials), 1)
        # 越权日志的操作者标识与普通操作日志保持一致，统一用账本成员标识
        writer_member = self.ctx.repos.members.find(self.ledger_id, self.writer.user_id)
        self.assertEqual(denials[0].actor_id, writer_member.member_id)

    def test_邀请链接不能授予管理员角色(self) -> None:
        """验证 REQ-046：管理员角色不能通过邀请链接授予。"""
        with self.assertRaises(BusinessRuleError):
            self.ctx.invitations.create_invitation(
                self.admin.user_id, self.ledger_id, Role.ADMIN
            )


class LeaveLedgerTest(LedgerTestCase):
    """成员退出与被移除的用例。"""

    def test_管理员不能被移出账本(self) -> None:
        """验证 REQ-005：管理员不能被移出账本。"""
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.members.remove_member(
                self.admin.user_id, self.ledger_id, self.admin.user_id
            )
        self.assertIn("管理员不能被移除", str(ctx.exception))
        self.assertEqual(self.member_of(self.admin).status, MemberStatus.ACTIVE)

    def test_管理员不能退出账本(self) -> None:
        """验证 REQ-005：管理员不能自行退出账本。"""
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.members.leave_ledger(self.admin.user_id, self.ledger_id)
        self.assertIn("管理员不能退出账本", str(ctx.exception))
        self.assertEqual(self.member_of(self.admin).status, MemberStatus.ACTIVE)

    def test_成员退出后结算资格失效(self) -> None:
        """验证 REQ-005：成员退出后不再参与后续结算。"""
        left = self.ctx.members.leave_ledger(self.writer.user_id, self.ledger_id)
        self.assertEqual(left.status, MemberStatus.LEFT)
        self.assertFalse(left.settlement_eligible)

    def test_成员退出后历史记录仍可查询且分摊明细不变(self) -> None:
        """验证 REQ-005、REQ-019：退出成员的记录仍可查，分摊快照不变。"""
        record = self.make_approved(
            self.writer,
            "90.00",
            payer_member_id=self.writer_member.member_id,
            participant_member_ids=[
                self.writer_member.member_id,
                self.admin_member.member_id,
            ],
        )
        before = self.ctx.repos.shares.list_by_record(record.record_id)
        self.ctx.members.leave_ledger(self.writer.user_id, self.ledger_id)

        page = self.ctx.records.query_records(
            self.admin.user_id, self.ledger_id, _all_filter()
        )
        self.assertTrue(any(item.record_id == record.record_id for item in page.items))
        after = self.ctx.repos.shares.list_by_record(record.record_id)
        self.assertEqual(
            sorted(item.amount for item in after),
            sorted(item.amount for item in before),
        )
        self.assertEqual(
            {item.member_id for item in after},
            {self.writer_member.member_id, self.admin_member.member_id},
        )

    def test_成员被移出账本后不再出现在新结算单中(self) -> None:
        """验证 REQ-005：被移出的成员不再参与后续结算。"""
        self.make_approved(
            self.writer,
            "90.00",
            payer_member_id=self.writer_member.member_id,
            participant_member_ids=[
                self.writer_member.member_id,
                self.admin_member.member_id,
            ],
        )
        self.ctx.members.remove_member(
            self.admin.user_id, self.ledger_id, self.writer.user_id
        )
        settlement = self.ctx.settlements.create_settlement(
            self.admin.user_id, self.ledger_id
        )
        member_ids = {item.member_id for item in settlement.members}
        self.assertNotIn(self.writer_member.member_id, member_ids)
        self.assertIn(self.admin_member.member_id, member_ids)

    def test_退出成员的历史金额仍计入成员统计(self) -> None:
        """验证 REQ-026：已退出成员的历史金额仍计入其统计结果。"""
        self.make_approved(
            self.writer,
            "90.00",
            payer_member_id=self.writer_member.member_id,
            participant_member_ids=[
                self.writer_member.member_id,
                self.admin_member.member_id,
            ],
        )
        self.ctx.members.leave_ledger(self.writer.user_id, self.ledger_id)
        stats = {
            item.dimension: item
            for item in self.ctx.statistics.member_statistics(
                self.admin.user_id, self.ledger_id
            )
        }
        self.assertEqual(stats[self.writer_member.member_id].expense, Decimal("45.00"))
        self.assertEqual(stats[self.admin_member.member_id].expense, Decimal("45.00"))


def _all_filter():
    """构造一个不带任何过滤条件的记录查询条件。"""
    from shared_ledger.persistence.repositories import RecordFilter

    return RecordFilter()

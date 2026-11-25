"""邀请链接的单元测试。

覆盖 REQ-002（邀请成员并指定加入角色）与 REQ-003（邀请链接的有效期与可使用次数），
并验证 REQ-006（退出成员重新加入后的结算资格）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from shared_ledger.domain.enums import InvitationStatus, MemberStatus, Role
from shared_ledger.domain.errors import BusinessRuleError, PermissionDeniedError

from tests.base import LedgerTestCase


class AcceptInvitationTest(LedgerTestCase):
    """通过邀请链接加入账本的用例。"""

    def test_通过邀请链接加入后角色即时生效(self) -> None:
        """验证 REQ-002：被邀请人通过链接进入后立即获得指定角色与相应权限。"""
        user = self.ctx.auth.register("newbie", "新人", "123456")
        invitation = self.ctx.invitations.create_invitation(
            self.admin.user_id, self.ledger_id, Role.WRITER
        )
        member = self.ctx.invitations.accept_invitation(invitation.token, user.user_id)
        self.assertEqual(member.role, Role.WRITER)
        self.assertEqual(member.status, MemberStatus.ACTIVE)
        self.assertTrue(member.settlement_eligible)

        record = self.create_draft(
            user,
            self.draft_input(
                "30.00",
                payer_member_id=member.member_id,
                participant_member_ids=[member.member_id],
            ),
        )
        self.assertEqual(record.status.value, "DRAFT")

    def test_只读角色加入后不能录入记录(self) -> None:
        """验证 REQ-002、REQ-044：以只读成员身份加入后立即不具备录入权限。"""
        user = self.ctx.auth.register("guest", "访客", "123456")
        invitation = self.ctx.invitations.create_invitation(
            self.admin.user_id, self.ledger_id, Role.READER
        )
        member = self.ctx.invitations.accept_invitation(invitation.token, user.user_id)
        self.assertEqual(member.role, Role.READER)
        self.assertFalse(member.settlement_eligible)
        with self.assertRaises(PermissionDeniedError):
            self.create_draft(
                user,
                self.draft_input(
                    "30.00",
                    payer_member_id=member.member_id,
                    participant_member_ids=[member.member_id],
                ),
            )

    def test_已是成员时重复接受邀请被拒绝(self) -> None:
        """验证 REQ-002：已是账本成员的用户不能通过邀请再次加入。"""
        invitation = self.ctx.invitations.create_invitation(
            self.admin.user_id, self.ledger_id, Role.WRITER
        )
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.invitations.accept_invitation(invitation.token, self.writer.user_id)
        self.assertIn("已经是该账本的成员", str(ctx.exception))

    def test_无效令牌被拒绝(self) -> None:
        """验证 REQ-002：令牌不存在的邀请链接不可使用。"""
        user = self.ctx.auth.register("nobody", "路人", "123456")
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.invitations.accept_invitation("not-a-token", user.user_id)
        self.assertIn("邀请链接无效", str(ctx.exception))


class InvitationValidityTest(LedgerTestCase):
    """邀请链接有效期与使用次数的用例。"""

    def test_过期邀请链接被拒绝并置为已过期(self) -> None:
        """验证 REQ-003：超过有效期的邀请链接不可使用，且状态变为已过期。"""
        user = self.ctx.auth.register("late", "迟到者", "123456")
        invitation = self.ctx.invitations.create_invitation(
            self.admin.user_id, self.ledger_id, Role.WRITER, valid_days=1
        )
        self.ctx.database.connection.execute(
            "UPDATE invitations SET expires_at = ? WHERE invitation_id = ?",
            (
                (datetime.now() - timedelta(hours=1)).isoformat(),
                invitation.invitation_id,
            ),
        )
        self.ctx.database.connection.commit()
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.invitations.accept_invitation(invitation.token, user.user_id)
        self.assertIn("邀请链接已过期", str(ctx.exception))
        stored = self.ctx.repos.invitations.find_by_id(invitation.invitation_id)
        self.assertEqual(stored.status, InvitationStatus.EXPIRED)

    def test_已撤销邀请链接被拒绝(self) -> None:
        """验证 REQ-003：管理员撤销后的邀请链接不可使用。"""
        user = self.ctx.auth.register("revoked", "被撤销者", "123456")
        invitation = self.ctx.invitations.create_invitation(
            self.admin.user_id, self.ledger_id, Role.WRITER
        )
        self.ctx.invitations.revoke_invitation(
            self.admin.user_id, self.ledger_id, invitation.invitation_id
        )
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.invitations.accept_invitation(invitation.token, user.user_id)
        self.assertIn("邀请链接已被撤销", str(ctx.exception))
        self.assertIsNone(self.ctx.repos.members.find(self.ledger_id, user.user_id))

    def test_邀请链接使用次数达上限后被拒绝(self) -> None:
        """验证 REQ-003：可使用次数用尽后再次使用链接被拒绝。"""
        invitation = self.ctx.invitations.create_invitation(
            self.admin.user_id, self.ledger_id, Role.WRITER, max_uses=2
        )
        first = self.ctx.auth.register("one", "甲", "123456")
        second = self.ctx.auth.register("two", "乙", "123456")
        third = self.ctx.auth.register("three", "丙", "123456")

        self.ctx.invitations.accept_invitation(invitation.token, first.user_id)
        self.ctx.invitations.accept_invitation(invitation.token, second.user_id)
        stored = self.ctx.repos.invitations.find_by_id(invitation.invitation_id)
        self.assertEqual(stored.used_count, 2)
        self.assertEqual(stored.status, InvitationStatus.USED)

        with self.assertRaises(BusinessRuleError):
            self.ctx.invitations.accept_invitation(invitation.token, third.user_id)
        self.assertIsNone(self.ctx.repos.members.find(self.ledger_id, third.user_id))

    def test_已使用的邀请不能再被撤销(self) -> None:
        """验证 REQ-003：已被使用的邀请不能撤销。"""
        user = self.ctx.auth.register("used", "使用者", "123456")
        invitation = self.ctx.invitations.create_invitation(
            self.admin.user_id, self.ledger_id, Role.WRITER
        )
        self.ctx.invitations.accept_invitation(invitation.token, user.user_id)
        with self.assertRaises(BusinessRuleError) as ctx:
            self.ctx.invitations.revoke_invitation(
                self.admin.user_id, self.ledger_id, invitation.invitation_id
            )
        self.assertIn("邀请已被使用", str(ctx.exception))


class RejoinLedgerTest(LedgerTestCase):
    """退出成员重新加入的用例。"""

    def test_退出成员重新加入后结算资格为假(self) -> None:
        """验证 REQ-006：曾退出账本的成员重新加入后不自动恢复结算资格。"""
        self.ctx.members.leave_ledger(self.writer.user_id, self.ledger_id)
        invitation = self.ctx.invitations.create_invitation(
            self.admin.user_id, self.ledger_id, Role.WRITER
        )
        member = self.ctx.invitations.accept_invitation(invitation.token, self.writer.user_id)
        self.assertEqual(member.role, Role.WRITER)
        self.assertEqual(member.status, MemberStatus.ACTIVE)
        self.assertFalse(member.settlement_eligible)

    def test_管理员显式恢复后结算资格恢复(self) -> None:
        """验证 REQ-006：管理员显式恢复结算资格后成员重新参与结算。"""
        self.ctx.members.leave_ledger(self.writer.user_id, self.ledger_id)
        invitation = self.ctx.invitations.create_invitation(
            self.admin.user_id, self.ledger_id, Role.WRITER
        )
        self.ctx.invitations.accept_invitation(invitation.token, self.writer.user_id)
        restored = self.ctx.members.restore_settlement_eligibility(
            self.admin.user_id, self.ledger_id, self.writer.user_id
        )
        self.assertTrue(restored.settlement_eligible)

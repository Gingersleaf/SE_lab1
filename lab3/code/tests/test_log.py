"""操作日志的单元测试。

覆盖 REQ-039（关键操作的日志记录）、REQ-040（日志的查询权限与不可删除）、
REQ-041（只读成员的操作日志可见范围）与 REQ-044（最小权限原则）。
"""

from __future__ import annotations

import unittest

from shared_ledger.domain.enums import LogActionType, Role
from shared_ledger.domain.errors import PermissionDeniedError

from tests.base import LedgerTestCase


class KeyOperationLogTest(LedgerTestCase):
    """关键操作写日志的用例。"""

    def _run_all_key_operations(self) -> None:
        """依次执行需求清单列出的全部关键操作。"""
        # 成员加入（邀请链接）
        newcomer = self.ctx.auth.register("newcomer", "新成员", "123456")
        self.join(newcomer, Role.WRITER)

        # 成员角色变更
        self.ctx.members.change_role(
            self.admin.user_id, self.ledger_id, self.reader.user_id, Role.WRITER
        )

        # 记录提交与审核通过
        approved = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, approved)
        self.approve(approved)

        # 记录驳回
        rejected = self.create_draft(self.writer, self.draft_input("20.00"))
        self.submit(self.writer, rejected)
        self.ctx.audits.reject(
            self.admin.user_id, self.ledger_id, rejected.record_id, "金额有误"
        )

        # 记录撤回
        withdrawn = self.create_draft(self.writer, self.draft_input("30.00"))
        self.submit(self.writer, withdrawn)
        self.ctx.records.withdraw(
            self.writer.user_id, self.ledger_id, withdrawn.record_id
        )

        # 记录作废
        voided = self.make_approved(self.writer, "40.00")
        self.ctx.audits.void_record(
            self.admin.user_id, self.ledger_id, voided.record_id, "重复录入"
        )

        # 发起冲正
        reversal = self.ctx.records.create_reversal(
            self.writer.user_id, self.ledger_id, approved.record_id
        )
        self.submit(self.writer, reversal)
        self.approve(reversal)

        # 管理员自审豁免
        self_record = self.create_draft(
            self.admin,
            self.draft_input(
                "50.00",
                payer_member_id=self.admin_member.member_id,
                participant_member_ids=[self.admin_member.member_id],
            ),
        )
        self.submit(self.admin, self_record)

        # 结算单生成、确认、申诉与裁决
        settlement = self.ctx.settlements.create_settlement(
            self.admin.user_id, self.ledger_id
        )
        settlement_id = settlement.settlement.settlement_id
        self.ctx.settlements.confirm(
            self.writer.user_id, self.ledger_id, settlement_id
        )
        self.ctx.settlements.appeal(
            self.writer.user_id, self.ledger_id, settlement_id, "分摊金额有疑问"
        )
        self.ctx.settlements.verdict(
            self.admin.user_id, self.ledger_id, settlement_id, "维持", "核对无误，维持本单"
        )

        # 成员退出
        self.ctx.members.leave_ledger(self.writer.user_id, self.ledger_id)

    def test_关键操作都写入了操作日志(self) -> None:
        """验证 REQ-039：逐项执行关键操作，核对每种动作类型都有日志。"""
        self._run_all_key_operations()
        actions = set(self.log_actions())
        expected = {
            LogActionType.MEMBER_JOIN.value,
            LogActionType.MEMBER_LEAVE.value,
            LogActionType.ROLE_CHANGE.value,
            LogActionType.RECORD_SUBMIT.value,
            LogActionType.RECORD_APPROVE.value,
            LogActionType.RECORD_REJECT.value,
            LogActionType.RECORD_WITHDRAW.value,
            LogActionType.RECORD_VOID.value,
            LogActionType.RECORD_REVERSE.value,
            LogActionType.SELF_REVIEW.value,
            LogActionType.SETTLEMENT_CREATE.value,
            LogActionType.SETTLEMENT_CONFIRM.value,
            LogActionType.SETTLEMENT_APPEAL.value,
            LogActionType.SETTLEMENT_VERDICT.value,
        }
        self.assertTrue(expected.issubset(actions), f"缺少的动作类型：{expected - actions}")

    def test_日志包含操作人对象标识时间与关键参数(self) -> None:
        """验证 REQ-039：每条日志包含操作人、操作类型、对象标识、时间与关键参数。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, record)
        logs = self.ctx.repos.logs.list_by_ledger(self.ledger_id)
        submit_logs = [
            item for item in logs if item.action is LogActionType.RECORD_SUBMIT
        ]
        self.assertEqual(len(submit_logs), 1)
        entry = submit_logs[0]
        self.assertEqual(entry.actor_id, self.writer_member.member_id)
        self.assertEqual(entry.target_id, record.record_id)
        self.assertEqual(entry.target_type, "收支记录")
        self.assertIn("100.00", entry.params)
        self.assertIsNotNone(entry.occurred_at)
        self.assertEqual(entry.ledger_id, self.ledger_id)

    def test_驳回原因与作废原因写入日志参数(self) -> None:
        """验证 REQ-039：驳回原因与作废原因作为关键参数写入日志。"""
        rejected = self.create_draft(self.writer, self.draft_input("20.00"))
        self.submit(self.writer, rejected)
        self.ctx.audits.reject(
            self.admin.user_id, self.ledger_id, rejected.record_id, "金额需复核"
        )
        voided = self.make_approved(self.writer, "40.00")
        self.ctx.audits.void_record(
            self.admin.user_id, self.ledger_id, voided.record_id, "重复录入"
        )
        logs = self.ctx.repos.logs.list_by_ledger(self.ledger_id)
        reject_log = next(
            item for item in logs if item.action is LogActionType.RECORD_REJECT
        )
        void_log = next(item for item in logs if item.action is LogActionType.RECORD_VOID)
        self.assertIn("金额需复核", reject_log.params)
        self.assertIn("重复录入", void_log.params)

    def test_结算裁决结论与理由写入日志(self) -> None:
        """验证 REQ-033、REQ-039：裁决结论与理由记入操作日志。"""
        self.make_approved(self.writer, "100.00")
        settlement = self.ctx.settlements.create_settlement(
            self.admin.user_id, self.ledger_id
        )
        settlement_id = settlement.settlement.settlement_id
        self.ctx.settlements.appeal(
            self.writer.user_id, self.ledger_id, settlement_id, "分摊金额有疑问"
        )
        self.ctx.settlements.verdict(
            self.admin.user_id, self.ledger_id, settlement_id, "维持", "核对无误"
        )
        logs = self.ctx.repos.logs.list_by_ledger(self.ledger_id)
        verdict_log = next(
            item for item in logs if item.action is LogActionType.SETTLEMENT_VERDICT
        )
        self.assertIn("维持", verdict_log.params)
        self.assertIn("核对无误", verdict_log.params)


class LogQueryPermissionTest(LedgerTestCase):
    """日志查询权限的用例。"""

    def test_管理员可查询全账本日志(self) -> None:
        """验证 REQ-040：管理员查询返回本账本全部日志。"""
        self.create_draft(self.writer, self.draft_input("100.00"))
        self.create_draft(
            self.admin,
            self.draft_input(
                "50.00",
                payer_member_id=self.admin_member.member_id,
                participant_member_ids=[self.admin_member.member_id],
            ),
        )
        page = self.ctx.logs.query(self.admin.user_id, self.ledger_id)
        all_logs = self.ctx.repos.logs.list_by_ledger(self.ledger_id)
        self.assertEqual(page.total, len(all_logs))
        self.assertGreater(page.total, 2)

    def test_记账成员只能查询与自己相关的日志(self) -> None:
        """验证 REQ-040：记账成员查询返回过滤后的自身相关日志。"""
        writer_record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, writer_record)
        self.approve(writer_record)
        self.create_draft(
            self.admin,
            self.draft_input(
                "50.00",
                payer_member_id=self.admin_member.member_id,
                participant_member_ids=[self.admin_member.member_id],
            ),
        )

        page = self.ctx.logs.query(self.writer.user_id, self.ledger_id)
        self.assertLess(page.total, len(self.ctx.repos.logs.list_by_ledger(self.ledger_id)))
        for item in page.items:
            self.assertTrue(
                item.actor_id == self.writer_member.member_id
                or item.target_id == self.writer_member.member_id
            )

    def test_管理员可按操作类型过滤日志(self) -> None:
        """验证 REQ-039：管理员可按操作类型查询日志。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        self.submit(self.writer, record)
        page = self.ctx.logs.query(
            self.admin.user_id, self.ledger_id, action=LogActionType.RECORD_SUBMIT
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].action, LogActionType.RECORD_SUBMIT)

    def test_只读成员查询日志被拒绝(self) -> None:
        """验证 REQ-041：只读成员查询操作日志被拒绝。"""
        with self.assertRaises(PermissionDeniedError):
            self.ctx.logs.query(self.reader.user_id, self.ledger_id)

    def test_只读成员查询日志被拒后留下越权日志(self) -> None:
        """验证 REQ-040、REQ-044：越权查询被拒绝时必须留下可审计的越权日志。

        只读成员查询操作日志会被拒绝，拦截不得静默丢弃，
        必须在操作日志中留下一条 ``ACCESS_DENIED`` 记录。
        """
        with self.assertRaises(PermissionDeniedError):
            self.ctx.logs.query(self.reader.user_id, self.ledger_id)
        denials = [
            item
            for item in self.ctx.repos.logs.list_by_ledger(self.ledger_id)
            if item.action is LogActionType.ACCESS_DENIED
        ]
        self.assertEqual(len(denials), 1)

    def test_日志只增不改不删(self) -> None:
        """验证 REQ-040：日志仓储不提供更新与删除方法，日志只能追加。"""
        for name in dir(self.ctx.repos.logs):
            self.assertNotIn("update", name.lower())
            self.assertNotIn("delete", name.lower())
            self.assertNotIn("remove", name.lower())

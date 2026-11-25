"""单元测试公共夹具。

所有测试类都继承本模块中的基类：

- :class:`ContextTestCase` 只负责建立独立的内存数据库上下文，
  满足「用例之间互相隔离」的要求；
- :class:`LedgerTestCase` 在此基础上预置一套完整的账本场景
  （管理员一名、记账成员一名、只读成员一名与五个默认分类），
  供业务层测试直接使用。
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from typing import List, Optional

from shared_ledger.app import ApplicationContext
from shared_ledger.domain.entities import Category, LedgerMember, Record
from shared_ledger.domain.enums import RecordType, Role
from shared_ledger.service.record_service import RecordDraftInput

DEFAULT_RECORD_DATE = date(2026, 11, 10)


class ContextTestCase(unittest.TestCase):
    """提供独立内存数据库上下文的测试基类。"""

    def setUp(self) -> None:
        """建立内存数据库上下文，保证用例之间互不影响。"""
        self.ctx = ApplicationContext(":memory:")

    def tearDown(self) -> None:
        """关闭数据库连接，释放资源。"""
        self.ctx.close()


class LedgerTestCase(ContextTestCase):
    """预置完整账本场景的测试基类。

    场景固定为：管理员「管理员」、记账成员「记账员」、只读成员「只读员」，
    账本「合租账本」下有系统默认的五个分类。
    """

    def setUp(self) -> None:
        """建立内存上下文并铺好账本、成员与分类。"""
        super().setUp()
        self.admin = self.ctx.auth.register("admin", "管理员", "123456")
        self.writer = self.ctx.auth.register("writer", "记账员", "123456")
        self.reader = self.ctx.auth.register("reader", "只读员", "123456")
        self.ledger = self.ctx.members.create_ledger(self.admin.user_id, "合租账本")
        self.ledger_id = self.ledger.ledger_id
        self.admin_member = self.member_of(self.admin)
        self.writer_member = self.join(self.writer, Role.WRITER)
        self.reader_member = self.join(self.reader, Role.READER)

    # ------------------------------------------------------------------
    # 夹具辅助方法
    # ------------------------------------------------------------------
    def join(self, user, role: Role = Role.WRITER) -> LedgerMember:
        """以管理员身份邀请并让指定用户加入账本。

        :param user: 待加入的用户。
        :param role: 邀请时指定的角色。
        :return: 加入后的成员关系。
        """
        invitation = self.ctx.invitations.create_invitation(
            self.admin.user_id, self.ledger_id, role
        )
        return self.ctx.invitations.accept_invitation(invitation.token, user.user_id)

    def member_of(self, user) -> LedgerMember:
        """返回用户在当前账本中的成员关系。"""
        member = self.ctx.repos.members.find(self.ledger_id, user.user_id)
        if member is None:
            raise AssertionError(f"用户 {user.account_name} 不在账本中")
        return member

    def category(self, name: str = "餐饮") -> Category:
        """按名称返回账本内的分类。"""
        for item in self.ctx.categories.list_categories(
            self.admin.user_id, self.ledger_id
        ):
            if item.name == name:
                return item
        raise AssertionError(f"账本中不存在分类 {name}")

    def draft_input(
        self,
        amount: str = "100.00",
        *,
        category: Optional[Category] = None,
        record_date: Optional[date] = None,
        payer_member_id: Optional[str] = None,
        participant_member_ids: Optional[List[str]] = None,
        record_type: RecordType = RecordType.EXPENSE,
        note: str = "",
    ) -> RecordDraftInput:
        """构造一条记录草稿的输入数据。"""
        target = category or self.category("餐饮")
        participants = participant_member_ids or [self.writer_member.member_id]
        return RecordDraftInput(
            record_type=record_type,
            amount=Decimal(amount),
            category_id=target.category_id,
            record_date=record_date or DEFAULT_RECORD_DATE,
            note=note,
            payer_member_id=payer_member_id or participants[0],
            participant_member_ids=list(participants),
        )

    def create_draft(
        self,
        user,
        payload: RecordDraftInput,
        request_id: str = "",
    ) -> Record:
        """以指定用户身份录入一条草稿记录。"""
        return self.ctx.records.create_draft(
            user.user_id, self.ledger_id, payload, request_id=request_id
        )

    def submit(self, user, record: Record, request_id: str = "") -> Record:
        """以指定用户身份提交记录审核。"""
        return self.ctx.records.submit(
            user.user_id, self.ledger_id, record.record_id, request_id=request_id
        )

    def approve(self, record: Record) -> Record:
        """以管理员身份审核通过记录。"""
        return self.ctx.audits.approve(self.admin.user_id, self.ledger_id, record.record_id)

    def make_approved(
        self,
        user=None,
        amount: str = "100.00",
        *,
        category: Optional[Category] = None,
        record_date: Optional[date] = None,
        payer_member_id: Optional[str] = None,
        participant_member_ids: Optional[List[str]] = None,
        record_type: RecordType = RecordType.EXPENSE,
        request_id: str = "",
    ) -> Record:
        """走完「录入 → 提交 → 审核通过」的完整流程，返回已通过记录。"""
        actor = user or self.writer
        payload = self.draft_input(
            amount,
            category=category,
            record_date=record_date,
            payer_member_id=payer_member_id,
            participant_member_ids=participant_member_ids,
            record_type=record_type,
        )
        record = self.create_draft(actor, payload, request_id=request_id)
        self.submit(actor, record)
        return self.approve(record)

    def log_actions(self) -> List[str]:
        """返回当前账本内全部日志的动作类型列表。"""
        return [
            item.action.value
            for item in self.ctx.repos.logs.list_by_ledger(self.ledger_id)
        ]

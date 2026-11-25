"""应用装配与测试夹具隔离性的自检用例。

本模块不针对具体业务需求，而是验证两件基础事实：

1. ``ApplicationContext`` 正确聚合了全部业务服务，模块装配没有遗漏；
2. 每个用例各自持有独立的内存数据库，用例之间数据互不可见。
"""

from __future__ import annotations

from shared_ledger.app import ApplicationContext
from shared_ledger.domain.entities import DEFAULT_CATEGORY_NAMES
from shared_ledger.domain.enums import Role
from shared_ledger.domain.errors import BusinessRuleError

from tests.base import ContextTestCase


class ApplicationContextTest(ContextTestCase):
    """应用上下文装配的用例。"""

    def test_上下文聚合了全部业务服务(self) -> None:
        """验证应用装配根把记录、审核、统计、预算、结算等服务一次性装配到位。"""
        for name in (
            "auth",
            "members",
            "invitations",
            "records",
            "audits",
            "categories",
            "statistics",
            "budgets",
            "settlements",
            "logs",
            "repos",
            "access",
        ):
            self.assertIsNotNone(getattr(self.ctx, name, None), f"缺少服务 {name}")

    def test_默认数据库为内存库(self) -> None:
        """验证单元测试使用的数据库路径为 ``:memory:``。"""
        self.assertEqual(self.ctx.database.path, ":memory:")

    def test_关闭上下文后连接被释放(self) -> None:
        """验证上下文关闭后数据库连接被释放，可重新建立连接。"""
        self.ctx.close()
        self.assertIsNone(self.ctx.database._connection)
        self.ctx.database.initialize()
        self.assertIsNotNone(self.ctx.database.connection)


class FixtureIsolationTest(ContextTestCase):
    """用例隔离性的用例。"""

    def test_两个上下文的账本数据互不可见(self) -> None:
        """验证用例之间互相隔离：另一个上下文看不到本用例的账本。"""
        user = self.ctx.auth.register("admin", "管理员", "123456")
        ledger = self.ctx.members.create_ledger(user.user_id, "隔离账本")
        other = ApplicationContext(":memory:")
        try:
            self.assertEqual(
                len(other.members.list_ledgers_for_user(user.user_id)), 0
            )
            with self.assertRaises(BusinessRuleError):
                other.members.get_ledger(ledger.ledger_id)
        finally:
            other.close()

    def test_新账本的默认分类与系统常量一致(self) -> None:
        """验证默认分类常量与账本创建时铺好的分类完全一致。"""
        user = self.ctx.auth.register("admin", "管理员", "123456")
        ledger = self.ctx.members.create_ledger(user.user_id, "默认分类账本")
        categories = self.ctx.categories.list_categories(user.user_id, ledger.ledger_id)
        self.assertEqual(
            tuple(item.name for item in categories), DEFAULT_CATEGORY_NAMES
        )
        self.assertEqual(categories[0].status.value, "ENABLED")

    def test_邀请加入后角色立即可判定(self) -> None:
        """验证权限守卫读取的是最新的成员角色，角色调整立即生效。"""
        admin = self.ctx.auth.register("admin", "管理员", "123456")
        guest = self.ctx.auth.register("guest", "访客", "123456")
        ledger = self.ctx.members.create_ledger(admin.user_id, "角色账本")
        invitation = self.ctx.invitations.create_invitation(
            admin.user_id, ledger.ledger_id, Role.READER
        )
        member = self.ctx.invitations.accept_invitation(invitation.token, guest.user_id)
        self.assertFalse(member.role.can_write_record)
        self.ctx.members.change_role(
            admin.user_id, ledger.ledger_id, guest.user_id, Role.WRITER
        )
        refreshed = self.ctx.repos.members.find(ledger.ledger_id, guest.user_id)
        self.assertTrue(refreshed.role.can_write_record)

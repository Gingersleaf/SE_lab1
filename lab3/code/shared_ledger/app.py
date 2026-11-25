"""多人共享记账系统 —— 应用装配根。

本模块是整个应用的组合根（Composition Root）：负责建立数据库连接、
创建仓储集合与全部业务服务，并把依赖关系一次装配好。

之所以要把装配集中在这里，是因为服务之间存在依赖
（结算服务依赖统计服务、日志服务依赖权限守卫），
如果让每个模块自己去取依赖，就会出现循环依赖与隐式耦合。
"""

from __future__ import annotations

from datetime import datetime

from .persistence.database import Database
from .persistence.repositories import RepositoryRegistry
from .service.access import AccessGuard
from .service.audit_service import AuditService
from .service.auth_service import AuthService
from .service.base import BaseService
from .service.budget_service import BudgetService
from .service.category_service import CategoryService
from .service.invitation_service import InvitationService
from .service.ledger_member_service import LedgerMemberService
from .service.log_service import LogService
from .service.record_service import RecordService
from .service.settlement_service import SettlementService
from .service.statistics_service import StatisticsService
from .support.idempotent_guard import IdempotentGuard


class ApplicationContext:
    """应用上下文，持有数据库与全部业务服务。"""

    def __init__(self, database_path: str = ":memory:") -> None:
        """初始化应用上下文。

        :param database_path: 数据库文件路径，``:memory:`` 表示内存数据库。
        """
        self.database = Database(database_path)
        self.database.initialize()
        self.repos = RepositoryRegistry(self.database)

        self.access = AccessGuard(self.repos)
        self.logs = LogService(self.repos, self.access)
        self.idempotent = IdempotentGuard(self.repos.dedups)

        self.auth = AuthService(self.repos)
        self.statistics = StatisticsService(self.repos, self.access)
        self.members = LedgerMemberService(self.repos, self.access, self.logs)
        self.invitations = InvitationService(self.repos, self.access, self.logs)
        self.records = RecordService(
            self.repos, self.access, self.logs, self.idempotent
        )
        self.audits = AuditService(self.repos, self.access, self.logs)
        self.categories = CategoryService(self.repos, self.access, self.logs)
        self.budgets = BudgetService(self.repos, self.access, self.logs, self.statistics)
        self.settlements = SettlementService(
            self.repos, self.access, self.logs, self.statistics
        )

    def close(self) -> None:
        """关闭数据库连接。"""
        self.database.close()

    def purge_expired_requests(self) -> int:
        """清理已过期的幂等记录，保留期为七天（REQ-035）。

        :return: 清理条数。
        """
        return self.idempotent.purge_expired(datetime.now())


__all__ = [
    "ApplicationContext",
    "AccessGuard",
    "AuditService",
    "AuthService",
    "BaseService",
    "BudgetService",
    "CategoryService",
    "Database",
    "IdempotentGuard",
    "InvitationService",
    "LedgerMemberService",
    "LogService",
    "RecordService",
    "RepositoryRegistry",
    "SettlementService",
    "StatisticsService",
]

"""角色权限守卫。

对应实验二类图中三类角色所体现的权限边界，也是 REQ-044 最小权限原则
在代码中的唯一落点。

所有业务服务在动手之前都先经过这里判定角色，
判定不通过时抛 ``PermissionDeniedError``，由服务层的统一包装器在事务
回滚之后补写越权日志——既不静默丢弃，也不会随业务事务一起回滚。

判定口径与实验二用例图完全一致：

- 管理员（ADMIN）：可用用例 UC001~UC004、UC012~UC014、UC017、UC025~UC028、UC029；
- 记账成员（WRITER）：在管理员之外可用 UC005~UC011、UC015、UC016；
- 只读成员（READER）：只可用 UC010、UC011，其余一律拒绝。
"""

from __future__ import annotations

from typing import NoReturn

from ..domain.entities import LedgerMember
from ..domain.enums import MemberStatus, Role
from ..domain.errors import NotFoundError, PermissionDeniedError
from ..persistence.repositories import RepositoryRegistry


class AccessGuard:
    """角色权限守卫。"""

    def __init__(self, repos: RepositoryRegistry) -> None:
        """初始化权限守卫。

        :param repos: 仓储集合。
        """
        self._repos = repos

    def member_of(self, ledger_id: str, user_id: str) -> LedgerMember:
        """查找用户在账本中的成员关系。

        :param ledger_id: 账本标识。
        :param user_id: 用户标识。
        :return: 成员关系。
        :raises NotFoundError: 用户不是该账本成员。
        """
        member = self._repos.members.find(ledger_id, user_id)
        if member is None:
            raise NotFoundError("你不是该账本的成员")
        return member

    def require_member(self, ledger_id: str, user_id: str) -> LedgerMember:
        """要求用户是该账本成员。

        :param ledger_id: 账本标识。
        :param user_id: 用户标识。
        :return: 成员关系。
        :raises PermissionDeniedError: 用户不是该账本成员。
        """
        member = self._repos.members.find(ledger_id, user_id)
        if member is None:
            raise PermissionDeniedError(
                "你不是该账本的成员",
                f"user {user_id} 未加入账本 {ledger_id}",
                ledger_id=ledger_id,
                actor_id=user_id,
                target_type="账本",
                target_id=ledger_id,
            )
        return member

    def require_active_member(self, ledger_id: str, user_id: str) -> LedgerMember:
        """要求用户是该账本的在册成员。

        已退出或被移除的成员不再具备操作资格（REQ-038）。

        :param ledger_id: 账本标识。
        :param user_id: 用户标识。
        :return: 成员关系。
        :raises PermissionDeniedError: 不是成员或已退出。
        """
        member = self.require_member(ledger_id, user_id)
        if member.status is not MemberStatus.ACTIVE:
            raise PermissionDeniedError(
                "成员已退出账本",
                f"成员 {member.member_id} 状态为 {member.status.value}",
                ledger_id=ledger_id,
                actor_id=user_id,
                target_type="账本成员",
                target_id=member.member_id,
            )
        return member

    def require_admin(self, ledger_id: str, user_id: str) -> LedgerMember:
        """要求用户是该账本的管理员。

        :param ledger_id: 账本标识。
        :param user_id: 用户标识。
        :return: 成员关系。
        :raises PermissionDeniedError: 角色不是管理员。
        """
        member = self.require_active_member(ledger_id, user_id)
        if member.role is not Role.ADMIN:
            self.deny(
                ledger_id,
                user_id,
                "账本成员",
                member.member_id,
                f"{member.role.display_name}无权执行管理员操作",
            )
        return member

    def require_writer(self, ledger_id: str, user_id: str) -> LedgerMember:
        """要求用户是记账成员或管理员。

        :param ledger_id: 账本标识。
        :param user_id: 用户标识。
        :return: 成员关系。
        :raises PermissionDeniedError: 角色为只读成员。
        """
        member = self.require_active_member(ledger_id, user_id)
        if not member.role.can_write_record:
            self.deny(
                ledger_id,
                user_id,
                "账本成员",
                member.member_id,
                "只读成员无权修改任何内容",
            )
        return member

    def require_reader(self, ledger_id: str, user_id: str) -> LedgerMember:
        """要求用户是该账本的任一在册成员，用于只读操作。

        :param ledger_id: 账本标识。
        :param user_id: 用户标识。
        :return: 成员关系。
        :raises PermissionDeniedError: 不是在册成员。
        """
        return self.require_active_member(ledger_id, user_id)

    def deny(
        self,
        ledger_id: str,
        actor_id: str,
        target_type: str,
        target_id: str,
        reason: str,
    ) -> NoReturn:
        """拒绝一次越权操作并抛出异常。

        :param ledger_id: 账本标识。
        :param actor_id: 尝试越权的操作者。
        :param target_type: 被操作的对象类型。
        :param target_id: 被操作的对象标识。
        :param reason: 拒绝原因。
        :raises PermissionDeniedError: 总是抛出。
        """
        raise PermissionDeniedError(
            "没有执行该操作的权限",
            reason,
            ledger_id=ledger_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
        )

    def is_admin(self, ledger_id: str, user_id: str) -> bool:
        """判断用户是否为该账本的管理员。

        :param ledger_id: 账本标识。
        :param user_id: 用户标识。
        :return: 是管理员时返回 ``True``。
        """
        member = self._repos.members.find(ledger_id, user_id)
        return member is not None and member.role is Role.ADMIN

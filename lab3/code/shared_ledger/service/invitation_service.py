"""邀请服务。

对应实验二组件图中的账本与成员模块 `InvitationService`。

覆盖 REQ-002 与 REQ-003。REQ-003（链接有效期与可使用次数）在需求分析阶段
标记为待确认，本实现按「可配置的有效期与使用次数」处理，
并把两者做成参数而不是写死，需求确认后调整默认值即可。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, List

from ..domain.entities import Invitation, LedgerMember
from ..domain.enums import InvitationStatus, LogActionType, MemberStatus, Role
from ..domain.errors import BusinessRuleError, ValidationError
from ..domain.support_ids import new_uuid
from ..persistence.repositories import RepositoryRegistry
from .base import BaseService, with_denial_log

DEFAULT_VALID_DAYS = 7
DEFAULT_MAX_USES = 1


class InvitationService(BaseService):
    """邀请服务。"""

    def __init__(
        self, repos: RepositoryRegistry, access: Any, logs: Any = None
    ) -> None:
        """初始化服务。

        :param repos: 仓储集合。
        :param access: 权限守卫。
        :param logs: 日志服务。
        """
        super().__init__(repos, access, logs)

    @with_denial_log
    def create_invitation(
        self,
        actor_user_id: str,
        ledger_id: str,
        invite_role: Role,
        valid_days: int = DEFAULT_VALID_DAYS,
        max_uses: int = DEFAULT_MAX_USES,
    ) -> Invitation:
        """生成邀请链接并指定加入后的角色。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :param invite_role: 加入后的角色，只能是记账成员或只读成员。
        :param valid_days: 链接有效期（天）。
        :param max_uses: 可使用次数。
        :return: 新建的邀请。
        :raises BusinessRuleError: 角色不允许通过邀请授予。
        """
        member = self.access.require_admin(ledger_id, actor_user_id)
        if invite_role is Role.ADMIN:
            raise BusinessRuleError("不支持通过邀请授予管理员角色")
        if valid_days <= 0 or max_uses <= 0:
            raise ValidationError("有效期与可使用次数必须为正数")

        now = datetime.now()
        invitation = Invitation(
            invitation_id=new_uuid(),
            token=new_uuid(),
            ledger_id=ledger_id,
            issuer_member_id=member.member_id,
            invite_role=invite_role,
            status=InvitationStatus.ISSUED,
            expires_at=now + timedelta(days=valid_days),
            used_count=0,
            max_uses=max_uses,
            created_at=now,
        )
        self.repos.invitations.save(invitation)
        return invitation

    @with_denial_log
    def revoke_invitation(
        self, actor_user_id: str, ledger_id: str, invitation_id: str
    ) -> Invitation:
        """撤销一条邀请链接。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :param invitation_id: 邀请标识。
        :return: 更新后的邀请。
        :raises BusinessRuleError: 邀请不存在或已被使用。
        """
        self.access.require_admin(ledger_id, actor_user_id)
        invitation = self.repos.invitations.find_by_id(invitation_id)
        if invitation is None or invitation.ledger_id != ledger_id:
            raise BusinessRuleError("邀请不存在")
        if invitation.status is InvitationStatus.USED:
            raise BusinessRuleError("邀请已被使用，无法撤销")
        invitation.status = InvitationStatus.REVOKED
        self.repos.invitations.save(invitation)
        return invitation

    @with_denial_log
    def accept_invitation(self, token: str, user_id: str) -> LedgerMember:
        """通过邀请链接加入账本。

        被邀请人通过链接进入后自动获得邀请时指定的角色，无需管理员二次审批
        （REQ-002）。曾退出账本的成员重新加入时不自动获得结算资格，
        需要管理员显式恢复（REQ-006）。

        :param token: 邀请令牌。
        :param user_id: 加入的用户标识。
        :return: 新建或更新后的成员关系。
        :raises BusinessRuleError: 链接无效、已过期、已撤销或已是成员。
        """
        invitation = self.repos.invitations.find_by_token(token or "")
        if invitation is None:
            raise BusinessRuleError("邀请链接无效")
        now = datetime.now()
        if invitation.status is InvitationStatus.REVOKED:
            raise BusinessRuleError("邀请链接已被撤销")
        if invitation.status is InvitationStatus.USED:
            raise BusinessRuleError("邀请链接已被使用")
        if invitation.expires_at <= now:
            invitation.status = InvitationStatus.EXPIRED
            self.repos.invitations.save(invitation)
            raise BusinessRuleError("邀请链接已过期")
        if invitation.used_count >= invitation.max_uses:
            raise BusinessRuleError("邀请链接的使用次数已用尽")

        existing = self.repos.members.find(invitation.ledger_id, user_id)
        if existing is not None and existing.status is MemberStatus.ACTIVE:
            raise BusinessRuleError("你已经是该账本的成员")

        joined_at = existing.joined_at if existing else now
        member = existing or LedgerMember(
            member_id=new_uuid(),
            user_id=user_id,
            ledger_id=invitation.ledger_id,
            joined_at=joined_at,
        )
        member.role = invitation.invite_role
        member.status = MemberStatus.ACTIVE
        member.settlement_eligible = invitation.invite_role is not Role.READER
        if existing is not None:
            member.settlement_eligible = False

        invitation.used_count += 1
        if invitation.used_count >= invitation.max_uses:
            invitation.status = InvitationStatus.USED

        with self.repos.database.transaction():
            self.repos.members.save(member)
            self.repos.invitations.save(invitation)
            self.logs.append_params(
                invitation.ledger_id,
                member.member_id,
                LogActionType.MEMBER_JOIN,
                "账本成员",
                member.member_id,
                {
                    "方式": "通过邀请链接加入",
                    "角色": invitation.invite_role.display_name,
                    "结算资格": "参与结算" if member.settlement_eligible else "需管理员恢复",
                },
            )
        return member

    @with_denial_log
    def list_invitations(
        self, actor_user_id: str, ledger_id: str
    ) -> List[Invitation]:
        """列出账本内的邀请链接。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :return: 邀请列表。
        """
        self.access.require_admin(ledger_id, actor_user_id)
        return self.repos.invitations.list_by_ledger(ledger_id)

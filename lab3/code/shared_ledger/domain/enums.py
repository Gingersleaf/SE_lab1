"""领域枚举。

本模块完整对应实验二 UML 类图「枚举（Enums）」分组中的八个枚举，字段与取值
必须与 `UML/UML类图.puml` 保持一致，任何一侧变更都要同步修改另一侧。

所有枚举均继承自 ``str``，这样既能用 ``==`` 做值比较，也能直接作为
SQLite 的 TEXT 列值存取，避免额外的序列化层。
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """账本成员角色，对应类图中的 `Role` 枚举。

    三类角色的能力是严格包含关系：只读成员 ⊂ 记账成员 ⊂ 管理员。
    """

    ADMIN = "ADMIN"
    WRITER = "WRITER"
    READER = "READER"

    @property
    def display_name(self) -> str:
        """返回角色的中文显示名。"""
        return {
            Role.ADMIN: "管理员",
            Role.WRITER: "记账成员",
            Role.READER: "只读成员",
        }[self]

    @property
    def can_write_record(self) -> bool:
        """判断该角色是否可以录入收支记录。

        只读成员只能查看，不能修改任何内容（REQ-044）。
        """
        return self in (Role.ADMIN, Role.WRITER)

    @property
    def can_audit_record(self) -> bool:
        """判断该角色是否可以执行审核类操作（通过、驳回、作废）。"""
        return self is Role.ADMIN

    @property
    def can_manage_member(self) -> bool:
        """判断该角色是否可以管理成员（邀请、改角色、移除）。"""
        return self is Role.ADMIN


class MemberStatus(str, Enum):
    """账本成员在册状态，对应类图中的 `MemberStatus` 枚举。"""

    ACTIVE = "ACTIVE"
    LEFT = "LEFT"

    @property
    def display_name(self) -> str:
        """返回状态的中文显示名。"""
        return {MemberStatus.ACTIVE: "在册", MemberStatus.LEFT: "已退出"}[self]


class InvitationStatus(str, Enum):
    """邀请链接状态，对应类图中的 `InvitationStatus` 枚举。"""

    ISSUED = "ISSUED"
    USED = "USED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"

    @property
    def display_name(self) -> str:
        """返回状态的中文显示名。"""
        return {
            InvitationStatus.ISSUED: "待使用",
            InvitationStatus.USED: "已使用",
            InvitationStatus.REVOKED: "已撤销",
            InvitationStatus.EXPIRED: "已过期",
        }[self]


class RecordStatus(str, Enum):
    """收支记录状态，对应类图中的 `RecordStatus` 枚举与状态图。"""

    DRAFT = "DRAFT"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"
    REVERSED = "REVERSED"

    @property
    def display_name(self) -> str:
        """返回状态的中文显示名。"""
        return {
            RecordStatus.DRAFT: "草稿",
            RecordStatus.PENDING: "待审核",
            RecordStatus.APPROVED: "已通过",
            RecordStatus.REJECTED: "已驳回",
            RecordStatus.VOIDED: "已作废",
            RecordStatus.REVERSED: "已冲正",
        }[self]

    @property
    def is_terminal(self) -> bool:
        """判断该状态是否为终态。

        已作废与已冲正是终态，不可再流转（REQ-015）。
        """
        return self in (RecordStatus.VOIDED, RecordStatus.REVERSED)

    @property
    def counted_in_statistics(self) -> bool:
        """判断该状态的记录是否计入统计。

        统计口径：仅统计已通过的记录（REQ-024）。
        """
        return self is RecordStatus.APPROVED


class RecordType(str, Enum):
    """收支类型，对应类图中的 `RecordType` 枚举。

    金额恒为正数，收支方向由本枚举表达而非依赖符号（REQ-017）。
    """

    EXPENSE = "EXPENSE"
    INCOME = "INCOME"

    @property
    def display_name(self) -> str:
        """返回类型的中文显示名。"""
        return {RecordType.EXPENSE: "支出", RecordType.INCOME: "收入"}[self]

    @property
    def sign(self) -> int:
        """返回该类型对账本净额的符号贡献。"""
        return -1 if self is RecordType.EXPENSE else 1


class CategoryStatus(str, Enum):
    """分类状态，对应类图中的 `CategoryStatus` 枚举。"""

    ENABLED = "ENABLED"
    DISABLED = "DISABLED"

    @property
    def display_name(self) -> str:
        """返回状态的中文显示名。"""
        return {CategoryStatus.ENABLED: "启用", CategoryStatus.DISABLED: "停用"}[self]


class SettlementStatus(str, Enum):
    """结算单状态，对应类图中的 `SettlementStatus` 枚举与状态图。"""

    PENDING_CONFIRM = "PENDING_CONFIRM"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"

    @property
    def display_name(self) -> str:
        """返回状态的中文显示名。"""
        return {
            SettlementStatus.PENDING_CONFIRM: "待确认",
            SettlementStatus.CONFIRMED: "已确认",
            SettlementStatus.DISPUTED: "有争议",
            SettlementStatus.VOIDED: "已作废",
        }[self]

    @property
    def is_terminal(self) -> bool:
        """判断该状态是否为终态。

        已确认与已作废是终态，已作废的结算单不可恢复（REQ-034）。
        """
        return self in (SettlementStatus.CONFIRMED, SettlementStatus.VOIDED)


class LogActionType(str, Enum):
    """操作日志动作类型，对应类图中的 `LogActionType` 枚举。"""

    MEMBER_JOIN = "MEMBER_JOIN"
    MEMBER_LEAVE = "MEMBER_LEAVE"
    ROLE_CHANGE = "ROLE_CHANGE"
    RECORD_SUBMIT = "RECORD_SUBMIT"
    RECORD_APPROVE = "RECORD_APPROVE"
    RECORD_REJECT = "RECORD_REJECT"
    RECORD_WITHDRAW = "RECORD_WITHDRAW"
    RECORD_VOID = "RECORD_VOID"
    RECORD_REVERSE = "RECORD_REVERSE"
    SELF_REVIEW = "SELF_REVIEW"
    SETTLEMENT_CREATE = "SETTLEMENT_CREATE"
    SETTLEMENT_CONFIRM = "SETTLEMENT_CONFIRM"
    SETTLEMENT_APPEAL = "SETTLEMENT_APPEAL"
    SETTLEMENT_VERDICT = "SETTLEMENT_VERDICT"
    ACCESS_DENIED = "ACCESS_DENIED"

    @property
    def display_name(self) -> str:
        """返回动作类型的中文显示名。"""
        return {
            LogActionType.MEMBER_JOIN: "成员加入",
            LogActionType.MEMBER_LEAVE: "成员退出",
            LogActionType.ROLE_CHANGE: "角色变更",
            LogActionType.RECORD_SUBMIT: "提交审核",
            LogActionType.RECORD_APPROVE: "审核通过",
            LogActionType.RECORD_REJECT: "审核驳回",
            LogActionType.RECORD_WITHDRAW: "撤回记录",
            LogActionType.RECORD_VOID: "作废记录",
            LogActionType.RECORD_REVERSE: "发起冲正",
            LogActionType.SELF_REVIEW: "管理员自审豁免",
            LogActionType.SETTLEMENT_CREATE: "生成结算单",
            LogActionType.SETTLEMENT_CONFIRM: "确认结算单",
            LogActionType.SETTLEMENT_APPEAL: "结算申诉",
            LogActionType.SETTLEMENT_VERDICT: "结算裁决",
            LogActionType.ACCESS_DENIED: "越权拒绝",
        }[self]

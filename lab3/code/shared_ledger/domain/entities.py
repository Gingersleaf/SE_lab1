"""领域实体。

本模块实现实验二 UML 类图中的十五个类。实体的字段与类图一一对应，
类图中没有画出的字段（如用户口令散列、记录的审核时间）属于实现必需的补充，
在类图修订时一并补上。

所有实体的主键统一使用 ``str`` 类型的 UUID4 字符串。
金额统一使用 ``decimal.Decimal``，避免浮点误差累积影响结算结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from .enums import (
    CategoryStatus,
    InvitationStatus,
    LogActionType,
    MemberStatus,
    RecordStatus,
    RecordType,
    Role,
    SettlementStatus,
)

DEFAULT_CATEGORY_NAMES = ("餐饮", "交通", "房租", "日用", "娱乐")


@dataclass
class User:
    """系统使用者实体，对应类图中的 `User` 类。

    用户与账本成员分离，使得同一个人可以在不同账本中拥有不同角色。
    """

    user_id: str
    account_name: str
    display_name: str
    status: str = "ACTIVE"
    password_hash: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_active(self) -> bool:
        """判断账号是否处于可用状态。"""
        return self.status == "ACTIVE"


@dataclass
class Ledger:
    """账本实体，对应类图中的 `Ledger` 类。

    ``member_limit`` 与 ``record_limit`` 来自 REQ-042 的规模上限，
    分别是 50 名成员与 10 万条记录。
    """

    ledger_id: str
    name: str
    admin_member_id: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    member_limit: int = 50
    record_limit: int = 100000

    @property
    def member_count_limit(self) -> int:
        """返回成员数量上限，与类图语义保持一致。"""
        return self.member_limit


@dataclass
class LedgerMember:
    """账本成员实体，对应类图中的 `LedgerMember` 类。

    角色与结算资格被拆成两个字段是有意为之：只读成员是因角色而无结算资格，
    已退出后被重新邀请的成员是因状态而无结算资格，两者成因不同，
    合并成一个字段会丢掉区分（参见实验二类图说明）。
    """

    member_id: str
    user_id: str
    ledger_id: str
    role: Role = Role.READER
    status: MemberStatus = MemberStatus.ACTIVE
    joined_at: datetime = field(default_factory=datetime.now)
    settlement_eligible: bool = False
    display_name: str = ""
    account_name: str = ""

    @property
    def is_active(self) -> bool:
        """判断成员当前是否仍在账本中。"""
        return self.status is MemberStatus.ACTIVE


@dataclass
class Invitation:
    """邀请链接实体，对应类图中的 `Invitation` 类。"""

    invitation_id: str
    token: str
    ledger_id: str
    issuer_member_id: str
    invite_role: Role = Role.WRITER
    status: InvitationStatus = InvitationStatus.ISSUED
    expires_at: datetime = field(default_factory=datetime.now)
    used_count: int = 0
    max_uses: int = 1
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Record:
    """收支记录实体，对应类图中的 `Record` 类。

    金额恒为正数，收支方向由 ``type`` 表达；``version`` 用于并发编辑校验，
    ``request_id`` 用于重复提交去重；``reversal_of_id`` 与 ``reversed_by_id``
    构成冲正记录与原记录的双向关联。
    """

    record_id: str
    ledger_id: str
    creator_id: str
    payer_id: str
    category_id: str
    type: RecordType = RecordType.EXPENSE
    amount: Decimal = Decimal("0.00")
    record_date: date = field(default_factory=date.today)
    note: str = ""
    status: RecordStatus = RecordStatus.DRAFT
    version: int = 1
    request_id: str = ""
    reversal_of_id: Optional[str] = None
    reversed_by_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reviewer_id: str = ""
    category_name: str = ""
    payer_name: str = ""
    creator_name: str = ""

    @property
    def signed_amount(self) -> Decimal:
        """返回带符号的金额，收入为正、支出为负。"""
        return self.amount * self.type.sign


@dataclass
class ShareItem:
    """分摊明细实体，对应类图中的 `ShareItem` 类。

    分摊明细在记录创建时确定并随记录保存为快照，成员增减或退出都不改变
    已有记录的分摊（REQ-019）。
    """

    share_id: str
    record_id: str
    member_id: str
    amount: Decimal = Decimal("0.00")
    is_remainder_holder: bool = False
    member_name: str = ""


@dataclass
class RecordTrace:
    """记录状态变更轨迹，对应类图中的 `RecordTrace` 类。

    保存原状态与新状态，使驳回原因、作废原因可追溯（REQ-045）。
    """

    trace_id: str
    record_id: str
    action: LogActionType = LogActionType.RECORD_SUBMIT
    actor_id: str = ""
    reason: str = ""
    from_status: Optional[RecordStatus] = None
    to_status: Optional[RecordStatus] = None
    occurred_at: datetime = field(default_factory=datetime.now)
    actor_name: str = ""


@dataclass
class Category:
    """分类实体，对应类图中的 `Category` 类。

    已被使用过的分类不可删除，只能停用（REQ-021）。
    """

    category_id: str
    ledger_id: str
    name: str
    is_default: bool = False
    status: CategoryStatus = CategoryStatus.ENABLED
    created_at: datetime = field(default_factory=datetime.now)
    record_count: int = 0


@dataclass
class Budget:
    """预算实体，对应类图中的 `Budget` 类。

    ``category_id`` 为空时表示账本总预算。
    """

    budget_id: str
    ledger_id: str
    category_id: Optional[str] = None
    amount: Decimal = Decimal("0.00")
    warning_ratio: Decimal = Decimal("0.9")
    created_by: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    category_name: str = ""


@dataclass
class StatResult:
    """统计结果值对象，对应类图中的 `StatResult` 类。

    由统计服务产出，不做持久化（REQ-024 口径由统计模块统一实现）。
    """

    dimension: str
    income: Decimal = Decimal("0.00")
    expense: Decimal = Decimal("0.00")
    net: Decimal = Decimal("0.00")
    month: str = ""
    label: str = ""

    @property
    def total(self) -> Decimal:
        """返回收支合计。"""
        return self.income + self.expense


@dataclass
class Settlement:
    """结算单实体，对应类图中的 `Settlement` 类。

    结算单在生成时把计算结果与涉及的记录存成快照，之后账本新增记录
    不追溯修改本单（REQ-034）。
    """

    settlement_id: str
    ledger_id: str
    status: SettlementStatus = SettlementStatus.PENDING_CONFIRM
    created_by: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    confirmed_at: Optional[datetime] = None
    verdict: str = ""
    verdict_reason: str = ""
    snapshot_record_ids: list = field(default_factory=list)
    record_snapshot: list = field(default_factory=list)


@dataclass
class SettlementMember:
    """结算成员实体，对应类图中的 `SettlementMember` 类。

    保存每位成员在本次结算中的净额快照与确认、申诉状态。
    """

    member_id: str
    settlement_id: str
    net_amount: Decimal = Decimal("0.00")
    confirmed: bool = False
    confirmed_at: Optional[datetime] = None
    appealed: bool = False
    appeal_reason: str = ""
    member_name: str = ""


@dataclass
class TransferPlanItem:
    """转账方案条目实体，对应类图中的 `TransferPlanItem` 类。

    条目由结算服务把净额拆成应收方与应付方两拨后依次配对生成（REQ-031）。
    """

    item_id: str
    settlement_id: str
    seq: int = 1
    from_member_id: str = ""
    to_member_id: str = ""
    amount: Decimal = Decimal("0.00")
    from_member_name: str = ""
    to_member_name: str = ""


@dataclass
class OperationLog:
    """操作日志实体，对应类图中的 `OperationLog` 类。

    日志只增不改不删，任何角色（含管理员）都不能修改或删除（REQ-040）。
    """

    log_id: str
    ledger_id: str
    actor_id: str = ""
    action: LogActionType = LogActionType.ACCESS_DENIED
    target_type: str = ""
    target_id: str = ""
    params: str = ""
    occurred_at: datetime = field(default_factory=datetime.now)
    actor_name: str = ""


@dataclass
class RequestDedup:
    """请求去重实体，对应类图中的 `RequestDedup` 类。

    服务端按请求标识保留七天，七天内重复提交返回首次结果（REQ-035）。
    """

    request_id: str
    user_id: str
    result_record_id: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    expire_at: datetime = field(default_factory=datetime.now)

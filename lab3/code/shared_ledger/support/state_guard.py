"""状态机校验。

对应实验二组件图中的支撑模块组件 `StateGuard`。

记录状态与结算单状态各自有一张允许的转换表，任何未列在表中的状态变更
一律拒绝并返回状态冲突提示（REQ-015、REQ-033、REQ-036）。

把状态机抽成独立组件而不是在每个接口里各写一遍判断，理由是：
同一条规则在不同入口出现不一致，是这类系统最常见的缺陷来源。
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Set

from ..domain.enums import RecordStatus, SettlementStatus
from ..domain.errors import StateConflictError

RECORD_TRANSITIONS: Dict[RecordStatus, FrozenSet[RecordStatus]] = {
    RecordStatus.DRAFT: frozenset({RecordStatus.PENDING, RecordStatus.APPROVED}),
    RecordStatus.PENDING: frozenset(
        {
            RecordStatus.APPROVED,
            RecordStatus.REJECTED,
            RecordStatus.DRAFT,
            RecordStatus.VOIDED,
        }
    ),
    RecordStatus.REJECTED: frozenset({RecordStatus.DRAFT, RecordStatus.PENDING}),
    RecordStatus.APPROVED: frozenset(
        {RecordStatus.VOIDED, RecordStatus.REVERSED}
    ),
    RecordStatus.VOIDED: frozenset(),
    RecordStatus.REVERSED: frozenset(),
}

SETTLEMENT_TRANSITIONS: Dict[SettlementStatus, FrozenSet[SettlementStatus]] = {
    SettlementStatus.PENDING_CONFIRM: frozenset(
        {SettlementStatus.CONFIRMED, SettlementStatus.DISPUTED}
    ),
    SettlementStatus.DISPUTED: frozenset(
        {SettlementStatus.CONFIRMED, SettlementStatus.VOIDED}
    ),
    SettlementStatus.CONFIRMED: frozenset(),
    SettlementStatus.VOIDED: frozenset(),
}

RECORD_ACTIONS: Dict[RecordStatus, List[str]] = {
    RecordStatus.DRAFT: ["编辑草稿", "提交审核"],
    RecordStatus.PENDING: ["审核通过", "审核驳回", "作废记录", "撤回记录"],
    RecordStatus.REJECTED: ["编辑草稿", "重新提交"],
    RecordStatus.APPROVED: ["作废记录", "发起冲正"],
    RecordStatus.VOIDED: [],
    RecordStatus.REVERSED: [],
}

SETTLEMENT_ACTIONS: Dict[SettlementStatus, List[str]] = {
    SettlementStatus.PENDING_CONFIRM: ["确认结算单", "结算申诉"],
    SettlementStatus.DISPUTED: ["结算裁决"],
    SettlementStatus.CONFIRMED: [],
    SettlementStatus.VOIDED: [],
}


class StateGuard:
    """状态机校验组件。"""

    @staticmethod
    def assert_record_transition(
        current: RecordStatus, target: RecordStatus, *, subject: str = "记录"
    ) -> None:
        """校验一条记录的状态流转是否合法。

        :param current: 当前状态。
        :param target: 目标状态。
        :param subject: 提示语中的对象名称。
        :raises StateConflictError: 流转不在允许的转换表中。
        """
        allowed: Set[RecordStatus] = set(RECORD_TRANSITIONS.get(current, frozenset()))
        if target not in allowed:
            raise StateConflictError(
                f"{subject}状态已变更，请刷新",
                f"当前状态 {current.display_name} 不允许变更为 {target.display_name}",
            )

    @staticmethod
    def assert_settlement_transition(
        current: SettlementStatus, target: SettlementStatus
    ) -> None:
        """校验一张结算单的状态流转是否合法。

        :param current: 当前状态。
        :param target: 目标状态。
        :raises StateConflictError: 流转不在允许的转换表中。
        """
        allowed: Set[SettlementStatus] = set(
            SETTLEMENT_TRANSITIONS.get(current, frozenset())
        )
        if target not in allowed:
            raise StateConflictError(
                "结算单状态已变更，请刷新",
                f"当前状态 {current.display_name} 不允许变更为 {target.display_name}",
            )

    @staticmethod
    def available_record_actions(status: RecordStatus) -> List[str]:
        """返回某状态下记录可执行的操作名称。

        :param status: 记录状态。
        :return: 操作名称列表，终态返回空列表。
        """
        return list(RECORD_ACTIONS.get(status, []))

    @staticmethod
    def available_settlement_actions(status: SettlementStatus) -> List[str]:
        """返回某状态下结算单可执行的操作名称。

        :param status: 结算单状态。
        :return: 操作名称列表，终态返回空列表。
        """
        return list(SETTLEMENT_ACTIONS.get(status, []))

    @staticmethod
    def is_record_terminal(status: RecordStatus) -> bool:
        """判断记录状态是否为终态。

        :param status: 记录状态。
        :return: 已作废或已冲正时返回 ``True``。
        """
        return status.is_terminal

"""状态机校验的单元测试（支撑层）。

对应支撑模块组件 ``StateGuard``，覆盖 REQ-015（收支记录状态流转规则）、
REQ-033（结算申诉与管理员裁决）与 REQ-036（状态冲突的拒绝与提示）。
"""

from __future__ import annotations

from shared_ledger.domain.enums import RecordStatus, SettlementStatus
from shared_ledger.domain.errors import StateConflictError
from shared_ledger.support.state_guard import (
    RECORD_TRANSITIONS,
    SETTLEMENT_TRANSITIONS,
    StateGuard,
)

from tests.base import ContextTestCase


class RecordStateMachineTest(ContextTestCase):
    """收支记录六状态流转规则的用例。"""

    def test_记录的合法流转全部通过(self) -> None:
        """验证 REQ-015：转换表中列出的每一种合法流转都被允许。"""
        for current, targets in RECORD_TRANSITIONS.items():
            for target in targets:
                StateGuard.assert_record_transition(current, target)

    def test_记录的非法流转全部被拒绝(self) -> None:
        """验证 REQ-015、REQ-036：不在转换表中的流转一律抛状态冲突异常。"""
        for current in RecordStatus:
            for target in RecordStatus:
                allowed = current in RECORD_TRANSITIONS and target in RECORD_TRANSITIONS[current]
                if allowed:
                    continue
                with self.assertRaises(StateConflictError):
                    StateGuard.assert_record_transition(current, target)

    def test_草稿可以提交为待审核(self) -> None:
        """验证 REQ-015：草稿 → 待审核属于合法流转。"""
        StateGuard.assert_record_transition(
            RecordStatus.DRAFT, RecordStatus.PENDING
        )

    def test_草稿不能直接被驳回(self) -> None:
        """验证 REQ-015：草稿不可直接变更为已驳回。"""
        with self.assertRaises(StateConflictError):
            StateGuard.assert_record_transition(
                RecordStatus.DRAFT, RecordStatus.REJECTED
            )

    def test_待审核可以撤回为草稿(self) -> None:
        """验证 REQ-011、REQ-015：待审核 → 草稿（撤回）属于合法流转。"""
        StateGuard.assert_record_transition(
            RecordStatus.PENDING, RecordStatus.DRAFT
        )

    def test_已驳回可以重新提交(self) -> None:
        """验证 REQ-010、REQ-015：已驳回 → 待审核属于合法流转。"""
        StateGuard.assert_record_transition(
            RecordStatus.REJECTED, RecordStatus.PENDING
        )

    def test_已作废是终态(self) -> None:
        """验证 REQ-015：已作废为终态，不可再流转到任何状态。"""
        for target in RecordStatus:
            with self.assertRaises(StateConflictError):
                StateGuard.assert_record_transition(RecordStatus.VOIDED, target)
        self.assertTrue(StateGuard.is_record_terminal(RecordStatus.VOIDED))

    def test_已冲正是终态(self) -> None:
        """验证 REQ-015：已冲正为终态，不可再流转到任何状态。"""
        for target in RecordStatus:
            with self.assertRaises(StateConflictError):
                StateGuard.assert_record_transition(RecordStatus.REVERSED, target)
        self.assertTrue(StateGuard.is_record_terminal(RecordStatus.REVERSED))

    def test_已通过不能退回草稿(self) -> None:
        """验证 REQ-015：已通过记录不可直接退回草稿。"""
        with self.assertRaises(StateConflictError):
            StateGuard.assert_record_transition(
                RecordStatus.APPROVED, RecordStatus.DRAFT
            )

    def test_各状态可用操作集合符合约定(self) -> None:
        """验证 REQ-015：每个状态下可执行的操作名称与状态图一致。"""
        self.assertEqual(
            StateGuard.available_record_actions(RecordStatus.DRAFT),
            ["编辑草稿", "提交审核"],
        )
        self.assertEqual(
            StateGuard.available_record_actions(RecordStatus.PENDING),
            ["审核通过", "审核驳回", "作废记录", "撤回记录"],
        )
        self.assertEqual(
            StateGuard.available_record_actions(RecordStatus.REJECTED),
            ["编辑草稿", "重新提交"],
        )
        self.assertEqual(
            StateGuard.available_record_actions(RecordStatus.APPROVED),
            ["作废记录", "发起冲正"],
        )
        self.assertEqual(StateGuard.available_record_actions(RecordStatus.VOIDED), [])
        self.assertEqual(StateGuard.available_record_actions(RecordStatus.REVERSED), [])


class SettlementStateMachineTest(ContextTestCase):
    """结算单四状态流转规则的用例。"""

    def test_结算单的合法流转全部通过(self) -> None:
        """验证 REQ-030、REQ-033：转换表中列出的合法流转都被允许。"""
        for current, targets in SETTLEMENT_TRANSITIONS.items():
            for target in targets:
                StateGuard.assert_settlement_transition(current, target)

    def test_结算单的非法流转全部被拒绝(self) -> None:
        """验证 REQ-036：不在转换表中的流转一律抛状态冲突异常。"""
        for current in SettlementStatus:
            for target in SettlementStatus:
                allowed = (
                    current in SETTLEMENT_TRANSITIONS
                    and target in SETTLEMENT_TRANSITIONS[current]
                )
                if allowed:
                    continue
                with self.assertRaises(StateConflictError):
                    StateGuard.assert_settlement_transition(current, target)

    def test_待确认可以变为已确认或有争议(self) -> None:
        """验证 REQ-032、REQ-033：待确认可确认，也可被申诉为有争议。"""
        StateGuard.assert_settlement_transition(
            SettlementStatus.PENDING_CONFIRM, SettlementStatus.CONFIRMED
        )
        StateGuard.assert_settlement_transition(
            SettlementStatus.PENDING_CONFIRM, SettlementStatus.DISPUTED
        )

    def test_有争议可以裁决为已确认或已作废(self) -> None:
        """验证 REQ-033：有争议的结算单可裁决为已确认或已作废。"""
        StateGuard.assert_settlement_transition(
            SettlementStatus.DISPUTED, SettlementStatus.CONFIRMED
        )
        StateGuard.assert_settlement_transition(
            SettlementStatus.DISPUTED, SettlementStatus.VOIDED
        )

    def test_已确认结算单不能再流转(self) -> None:
        """验证 REQ-033：已确认是终态，不能再申诉也不能再裁决。"""
        for target in SettlementStatus:
            with self.assertRaises(StateConflictError):
                StateGuard.assert_settlement_transition(
                    SettlementStatus.CONFIRMED, target
                )

    def test_已作废结算单不能再流转(self) -> None:
        """验证 REQ-034：已作废是终态，不可恢复为有效状态。"""
        for target in SettlementStatus:
            with self.assertRaises(StateConflictError):
                StateGuard.assert_settlement_transition(
                    SettlementStatus.VOIDED, target
                )

    def test_结算单可用操作集合符合约定(self) -> None:
        """验证 REQ-033：每个状态下可执行的操作名称与状态图一致。"""
        self.assertEqual(
            StateGuard.available_settlement_actions(SettlementStatus.PENDING_CONFIRM),
            ["确认结算单", "结算申诉"],
        )
        self.assertEqual(
            StateGuard.available_settlement_actions(SettlementStatus.DISPUTED),
            ["结算裁决"],
        )
        self.assertEqual(
            StateGuard.available_settlement_actions(SettlementStatus.CONFIRMED), []
        )
        self.assertEqual(
            StateGuard.available_settlement_actions(SettlementStatus.VOIDED), []
        )

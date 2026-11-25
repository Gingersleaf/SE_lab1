"""结算服务。

对应实验二组件图中的结算模块 `SettlementService`。

覆盖 REQ-030 至 REQ-034：

- 管理员基于已通过且未被冲正的记录发起结算，生成结算单快照；
- 结算单把成员净额拆成应收方与应付方两拨，按金额排序依次配对，
  生成条目数尽量少的转账方案；
- 参与成员逐个确认，全部确认完毕后结算单变为已确认；
- 成员可申诉，管理员裁决维持或作废；
- 结算单生成后即与记录解耦，之后新增记录不追溯修改本单。

关键约束：结算模块**只读记录表**，绝不回写记录。
结算单把计算结果存成快照，这既是 REQ-034 的要求，
也让结算逻辑不会反过来污染统计口径。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from ..domain.entities import Settlement, SettlementMember, TransferPlanItem
from ..domain.enums import LogActionType, MemberStatus, SettlementStatus
from ..domain.errors import BusinessRuleError, StateConflictError, ValidationError
from ..domain.support_ids import new_settlement_id, new_uuid
from ..persistence.repositories import RepositoryRegistry
from ..support.state_guard import StateGuard
from .base import BaseService, with_denial_log

ZERO = Decimal("0.00")
VERDICT_MAINTAIN = "维持"
VERDICT_VOID = "作废"


@dataclass
class SettlementDetail:
    """结算单详情所需的全部数据。"""

    settlement: Settlement
    members: List[SettlementMember] = field(default_factory=list)
    plan: List[TransferPlanItem] = field(default_factory=list)
    confirmed_count: int = 0
    total_members: int = 0
    ledger_net: Decimal = ZERO

    @property
    def all_confirmed(self) -> bool:
        """判断是否已完成全员确认。"""
        return 0 < self.total_members <= self.confirmed_count


class SettlementService(BaseService):
    """结算服务。"""

    def __init__(
        self,
        repos: RepositoryRegistry,
        access: Any,
        logs: Any = None,
        statistics: Any = None,
    ) -> None:
        """初始化服务。

        :param repos: 仓储集合。
        :param access: 权限守卫。
        :param logs: 日志服务。
        :param statistics: 统计服务，结算取数只经由它。
        """
        super().__init__(repos, access, logs)
        self.statistics = statistics

    @with_denial_log
    def create_settlement(
        self, actor_user_id: str, ledger_id: str
    ) -> SettlementDetail:
        """发起结算并生成结算单。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :return: 生成的结算单详情。
        :raises BusinessRuleError: 没有可参与结算的记录或成员。
        """
        member = self.access.require_admin(ledger_id, actor_user_id)
        entries = (
            self.statistics.counted_entries(ledger_id) if self.statistics else []
        )
        if not entries:
            raise BusinessRuleError("账本内没有可参与结算的记录")

        nets = self._compute_member_nets(ledger_id, entries)
        eligible = {
            item.member_id
            for item in self.repos.members.list_by_ledger(ledger_id)
            if item.status is MemberStatus.ACTIVE and item.settlement_eligible
        }
        participants = {
            key: value for key, value in nets.items() if key in eligible
        }
        if not participants:
            raise BusinessRuleError("没有具备结算资格的成员")

        now = datetime.now()
        settlement = Settlement(
            settlement_id=new_settlement_id(now),
            ledger_id=ledger_id,
            status=SettlementStatus.PENDING_CONFIRM,
            created_by=member.member_id,
            created_at=now,
            snapshot_record_ids=[entry.record.record_id for entry in entries],
        )

        member_rows: List[SettlementMember] = []
        for member_id, net in sorted(
            participants.items(), key=lambda item: item[1], reverse=True
        ):
            member_row = SettlementMember(
                member_id=member_id,
                settlement_id=settlement.settlement_id,
                net_amount=net.quantize(Decimal("0.01")),
            )
            member_rows.append(member_row)

        plan = self._build_plan(settlement.settlement_id, participants)

        with self.repos.database.transaction():
            self.repos.settlements.save(settlement)
            for row in member_rows:
                self.repos.settlement_members.save(row)
            self.repos.transfer_plans.save_many(plan)
            self.logs.append_params(
                ledger_id,
                member.member_id,
                LogActionType.SETTLEMENT_CREATE,
                "结算单",
                settlement.settlement_id,
                {
                    "纳入已通过记录": len(entries),
                    "涉及成员": len(member_rows),
                    "账本净额": str(self._ledger_net(entries)),
                },
            )
        return self._detail(settlement)

    @with_denial_log
    def confirm(
        self, actor_user_id: str, ledger_id: str, settlement_id: str
    ) -> SettlementDetail:
        """成员确认结算单。

        对已确认的成员重复确认按幂等处理，不产生重复记录（REQ-032）。

        :param actor_user_id: 操作者，必须是参与成员。
        :param ledger_id: 账本标识。
        :param settlement_id: 结算单标识。
        :return: 更新后的结算单详情。
        :raises BusinessRuleError: 不是参与成员。
        :raises StateConflictError: 结算单状态已变更。
        """
        member = self.access.require_active_member(ledger_id, actor_user_id)
        settlement = self._require_settlement(ledger_id, settlement_id)
        StateGuard.assert_settlement_transition(
            settlement.status, SettlementStatus.CONFIRMED
        )

        row = self.repos.settlement_members.find(settlement_id, member.member_id)
        if row is None:
            self.access.deny(
                ledger_id,
                actor_user_id,
                "结算单",
                settlement_id,
                "不是该结算单的参与成员",
            )

        if row.confirmed:
            return self._detail(settlement)

        now = datetime.now()
        row.confirmed = True
        row.confirmed_at = now

        with self.repos.database.transaction():
            self.repos.settlement_members.save(row)
            members = self.repos.settlement_members.list_by_settlement(settlement_id)
            if members and all(item.confirmed for item in members):
                settlement.status = SettlementStatus.CONFIRMED
                settlement.confirmed_at = now
                self.repos.settlements.save(settlement)
            self.logs.append_params(
                ledger_id,
                member.member_id,
                LogActionType.SETTLEMENT_CONFIRM,
                "结算单",
                settlement_id,
                {"状态": settlement.status.display_name},
            )
        return self._detail(settlement)

    @with_denial_log
    def appeal(
        self,
        actor_user_id: str,
        ledger_id: str,
        settlement_id: str,
        reason: str,
    ) -> SettlementDetail:
        """对结算单发起申诉。

        :param actor_user_id: 操作者，必须是参与成员。
        :param ledger_id: 账本标识。
        :param settlement_id: 结算单标识。
        :param reason: 申诉原因，必填。
        :return: 更新后的结算单详情。
        :raises ValidationError: 未填写申诉原因。
        :raises StateConflictError: 结算单状态已变更。
        """
        member = self.access.require_active_member(ledger_id, actor_user_id)
        text = (reason or "").strip()
        if not text:
            raise ValidationError("必须填写申诉原因")
        settlement = self._require_settlement(ledger_id, settlement_id)
        StateGuard.assert_settlement_transition(
            settlement.status, SettlementStatus.DISPUTED
        )

        row = self.repos.settlement_members.find(settlement_id, member.member_id)
        if row is None:
            self.access.deny(
                ledger_id,
                actor_user_id,
                "结算单",
                settlement_id,
                "不是该结算单的参与成员",
            )

        row.appealed = True
        row.appeal_reason = text
        settlement.status = SettlementStatus.DISPUTED

        with self.repos.database.transaction():
            self.repos.settlement_members.save(row)
            self.repos.settlements.save(settlement)
            self.logs.append_params(
                ledger_id,
                member.member_id,
                LogActionType.SETTLEMENT_APPEAL,
                "结算单",
                settlement_id,
                {"申诉原因": text},
            )
        return self._detail(settlement)

    @with_denial_log
    def verdict(
        self,
        actor_user_id: str,
        ledger_id: str,
        settlement_id: str,
        result: str,
        reason: str,
    ) -> SettlementDetail:
        """管理员对争议结算单作出裁决。

        裁决结果为维持则结算单直接变为已确认，为作废则变为已作废；
        裁决后不再要求成员重新确认（REQ-033）。

        :param actor_user_id: 操作者，必须是管理员。
        :param ledger_id: 账本标识。
        :param settlement_id: 结算单标识。
        :param result: 裁决结论，维持或作废。
        :param reason: 裁决理由，必填。
        :return: 更新后的结算单详情。
        :raises ValidationError: 结论或理由不合法。
        :raises StateConflictError: 结算单状态已变更。
        """
        member = self.access.require_admin(ledger_id, actor_user_id)
        text = (reason or "").strip()
        if not text:
            raise ValidationError("必须填写裁决理由")
        if result not in (VERDICT_MAINTAIN, VERDICT_VOID):
            raise ValidationError("裁决结论只能是维持或作废")
        settlement = self._require_settlement(ledger_id, settlement_id)
        if settlement.status is not SettlementStatus.DISPUTED:
            raise StateConflictError(
                "结算单状态已变更，请刷新",
                f"当前状态 {settlement.status.display_name} 没有争议，无需裁决",
            )
        StateGuard.assert_settlement_transition(
            settlement.status, SettlementStatus.CONFIRMED
        )

        target = (
            SettlementStatus.CONFIRMED
            if result == VERDICT_MAINTAIN
            else SettlementStatus.VOIDED
        )
        StateGuard.assert_settlement_transition(settlement.status, target)
        settlement.status = target
        settlement.verdict = result
        settlement.verdict_reason = text
        settlement.confirmed_at = datetime.now()

        with self.repos.database.transaction():
            self.repos.settlements.save(settlement)
            self.logs.append_params(
                ledger_id,
                member.member_id,
                LogActionType.SETTLEMENT_VERDICT,
                "结算单",
                settlement_id,
                {"结论": result, "理由": text},
            )
        return self._detail(settlement)

    @with_denial_log
    def get_settlement(
        self, actor_user_id: str, ledger_id: str, settlement_id: str
    ) -> SettlementDetail:
        """查看结算单详情。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :param settlement_id: 结算单标识。
        :return: 结算单详情。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        settlement = self._require_settlement(ledger_id, settlement_id)
        return self._detail(settlement)

    @with_denial_log
    def list_settlements(
        self, actor_user_id: str, ledger_id: str
    ) -> List[Settlement]:
        """列出账本内的全部结算单。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :return: 结算单列表。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        return self.repos.settlements.list_by_ledger(ledger_id)

    def _require_settlement(self, ledger_id: str, settlement_id: str) -> Settlement:
        """查找结算单并校验其属于指定账本。

        :param ledger_id: 账本标识。
        :param settlement_id: 结算单标识。
        :return: 结算单实体。
        :raises BusinessRuleError: 结算单不存在。
        """
        settlement = self.repos.settlements.find_by_id(settlement_id)
        if settlement is None or settlement.ledger_id != ledger_id:
            raise BusinessRuleError("结算单不存在")
        return settlement

    def _detail(self, settlement: Settlement) -> SettlementDetail:
        """组装结算单详情。

        :param settlement: 结算单实体。
        :return: 结算单详情。
        """
        members = self.repos.settlement_members.list_by_settlement(
            settlement.settlement_id
        )
        plan = self.repos.transfer_plans.list_by_settlement(settlement.settlement_id)
        confirmed = len([item for item in members if item.confirmed])
        ledger_net = ZERO
        if self.statistics is not None:
            ledger_net = self.statistics.total_net(settlement.ledger_id)
        return SettlementDetail(
            settlement=settlement,
            members=members,
            plan=plan,
            confirmed_count=confirmed,
            total_members=len(members),
            ledger_net=ledger_net,
        )

    def _compute_member_nets(
        self, ledger_id: str, entries: List
    ) -> Dict[str, Decimal]:
        """按分摊明细计算每位成员的净额。

        成员净额之和等于账本净额（REQ-030）。

        :param ledger_id: 账本标识。
        :param entries: 参与统计的记录。
        :return: 成员标识到净额的映射。
        """
        shares_by_record: Dict[str, List] = {}
        for share in self.repos.shares.list_by_ledger(ledger_id):
            shares_by_record.setdefault(share.record_id, []).append(share)

        nets: Dict[str, Decimal] = {}
        for entry in entries:
            record = entry.record
            sign = 1 if record.type.value == "INCOME" else -1
            for share in shares_by_record.get(record.record_id, []):
                current = nets.get(share.member_id, ZERO)
                nets[share.member_id] = current + share.amount * sign * entry.direction
        return nets

    @staticmethod
    def _ledger_net(entries: List) -> Decimal:
        """按参与结算的记录计算账本净额。

        :param entries: 参与统计的记录。
        :return: 账本净额。
        """
        total = ZERO
        for entry in entries:
            total += entry.record.signed_amount * entry.direction
        return total.quantize(Decimal("0.01"))

    @staticmethod
    def _build_plan(
        settlement_id: str, nets: Dict[str, Decimal]
    ) -> List[TransferPlanItem]:
        """生成转账方案。

        把成员净额拆成应收方与应付方两拨，配对方式分两轮：

        第一轮先配对**剩余金额完全相等**的两方。这类配对一次就能结清双方，
        是条目数最省的配法，先做这一轮可以显著减少条目数；
        第二轮再按金额从大到小依次配对，每轮取双方剩余金额的较小值
        作为转账金额，金额大的优先配对，尽量让条目数接近最少。

        :param settlement_id: 结算单标识。
        :param nets: 成员标识到净额的映射。
        :return: 转账条目列表。
        """
        payers = {
            member_id: -net for member_id, net in nets.items() if net < 0
        }
        receivers = {
            member_id: net for member_id, net in nets.items() if net > 0
        }
        plan: List[TransferPlanItem] = []
        seq = 1

        for payer_id in list(payers.keys()):
            if payers[payer_id] <= 0:
                continue
            for receiver_id in list(receivers.keys()):
                if receivers[receiver_id] <= 0:
                    continue
                if payers[payer_id] == receivers[receiver_id]:
                    plan.append(
                        TransferPlanItem(
                            item_id=new_uuid(),
                            settlement_id=settlement_id,
                            seq=seq,
                            from_member_id=payer_id,
                            to_member_id=receiver_id,
                            amount=payers[payer_id].quantize(Decimal("0.01")),
                        )
                    )
                    seq += 1
                    payers[payer_id] = Decimal("0.00")
                    receivers[receiver_id] = Decimal("0.00")
                    break

        payer_list = sorted(
            [(key, value) for key, value in payers.items() if value > 0],
            key=lambda item: item[1],
            reverse=True,
        )
        receiver_list = sorted(
            [(key, value) for key, value in receivers.items() if value > 0],
            key=lambda item: item[1],
            reverse=True,
        )

        index_p = 0
        index_r = 0
        while index_p < len(payer_list) and index_r < len(receiver_list):
            payer_id, payer_left = payer_list[index_p]
            receiver_id, receiver_left = receiver_list[index_r]
            amount = min(payer_left, receiver_left)
            if amount > 0:
                plan.append(
                    TransferPlanItem(
                        item_id=new_uuid(),
                        settlement_id=settlement_id,
                        seq=seq,
                        from_member_id=payer_id,
                        to_member_id=receiver_id,
                        amount=amount.quantize(Decimal("0.01")),
                    )
                )
                seq += 1
            payer_left -= amount
            receiver_left -= amount
            payer_list[index_p] = (payer_id, payer_left)
            receiver_list[index_r] = (receiver_id, receiver_left)
            if payer_left <= 0:
                index_p += 1
            if receiver_left <= 0:
                index_r += 1
        return plan

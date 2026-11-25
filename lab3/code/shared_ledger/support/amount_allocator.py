"""金额校验与分摊算法。

对应实验二组件图中的支撑模块组件 `AmountAllocator`。

本模块集中实现三条互相耦合的规则，抽出来单独成组件的理由是：
它们会被记录服务、统计服务、结算服务共同使用，各写一份必然出现行为不一致。

1. REQ-017 金额必须大于零、精确到分、最多两位小数；
2. REQ-018 单条记录金额上限 500000.00 元；
3. REQ-019 分摊按参与成员均摊，除不尽的余数分配给加入账本最早的一位；
4. REQ-020 分摊金额之和必须等于记录金额。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence

from ..domain.errors import ValidationError

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class ShareAllocation:
    """一次分摊计算的结果条目。

    对应类图中的 `ShareItem` 的值对象形式：只描述「谁分到多少」，
    真正的持久化由记录服务负责。
    """

    member_id: str
    amount: Decimal
    is_remainder_holder: bool


@dataclass(frozen=True)
class Participant:
    """参与分摊的成员及其加入账本的时间。

    加入时间是余数归属的判定依据，因此必须随成员一起传入，
    不能在算法内部去查数据库，否则算法就不成其为纯粹的横切组件。
    """

    member_id: str
    joined_at: datetime


class AmountAllocator:
    """金额与分摊算法组件。"""

    MAX_RECORD_AMOUNT = Decimal("500000.00")
    MAX_DECIMAL_PLACES = 2
    MIN_PARTICIPANTS = 1

    @classmethod
    def validate_amount(
        cls,
        amount: Decimal,
        *,
        field_name: str = "金额",
        check_limit: bool = True,
    ) -> Decimal:
        """校验并归一化单条记录的金额。

        :param amount: 待校验的金额。
        :param field_name: 用于提示语的字段名。
        :param check_limit: 是否校验单笔上限。REQ-018 规定超限金额允许以
            草稿形式保存但不允许提交，因此草稿保存阶段不校验上限，
            正式提交阶段才校验。
        :return: 归一化到两位小数的金额。
        :raises ValidationError: 金额非正数、精度超过两位小数或超过单笔上限。
        """
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(f"{field_name}不是有效数字") from exc

        if not value.is_finite():
            raise ValidationError(f"{field_name}不是有效数字")

        if value <= 0:
            raise ValidationError(f"{field_name}必须大于零")

        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > cls.MAX_DECIMAL_PLACES:
            raise ValidationError(f"{field_name}最多保留两位小数")

        if check_limit and value > cls.MAX_RECORD_AMOUNT:
            raise ValidationError(
                f"{field_name}超出单笔限额，最大为 {cls.MAX_RECORD_AMOUNT} 元"
            )
        return value.quantize(CENTS)

    @classmethod
    def validate_budget_amount(cls, amount: Decimal) -> Decimal:
        """校验并归一化预算金额。

        预算与记录金额的规则不同：预算同样必须为正数、至多两位小数，
        但不受单笔 500000.00 元上限约束（REQ-028）。

        :param amount: 待校验的预算金额。
        :return: 归一化到两位小数的预算金额。
        :raises ValidationError: 金额非正数或精度超过两位小数。
        """
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("预算金额不是有效数字") from exc

        if not value.is_finite() or value <= 0:
            raise ValidationError("预算金额必须大于零")

        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > cls.MAX_DECIMAL_PLACES:
            raise ValidationError("预算金额最多保留两位小数")
        return value.quantize(CENTS)

    @classmethod
    def split_evenly(
        cls, total: Decimal, participants: Sequence[Participant]
    ) -> list:
        """把总金额均摊给参与成员。

        除不尽的余数（不足一分的尾差）整体分配给加入账本最早的一位参与者。
        这里刻意不做「每人轮流多拿一分」的处理：需求原文是「余数分配给
        参与分摊成员中加入账本最早的一位」，只有一种归属才与原文一致，
        也才能在记录详情里标出唯一的「余数归属者」。

        :param total: 需要分摊的总金额。
        :param participants: 参与分摊的成员列表。
        :return: 分摊结果列表，顺序与传入的参与者一致。
        :raises ValidationError: 参与人数不足或总金额非法。
        """
        amount = cls.validate_amount(total, field_name="记录金额", check_limit=False)
        if len(participants) < cls.MIN_PARTICIPANTS:
            raise ValidationError("至少需要一名成员参与分摊")

        member_ids = [item.member_id for item in participants]
        if len(set(member_ids)) != len(member_ids):
            raise ValidationError("参与分摊的成员中出现重复人员")

        total_cents = int((amount * 100).to_integral_value())
        count = len(participants)
        base_cents, remainder = divmod(total_cents, count)

        earliest_index = min(
            range(count), key=lambda idx: (participants[idx].joined_at, idx)
        )

        allocations = []
        for index, participant in enumerate(participants):
            cents = base_cents
            is_holder = False
            if index == earliest_index:
                cents += remainder
                is_holder = remainder > 0
            allocations.append(
                ShareAllocation(
                    member_id=participant.member_id,
                    amount=(Decimal(cents) / 100).quantize(CENTS),
                    is_remainder_holder=is_holder,
                )
            )
        return allocations

    @classmethod
    def validate_share_sum(
        cls, record_amount: Decimal, share_amounts: Sequence[Decimal]
    ) -> None:
        """校验分摊金额之和与记录金额一致。

        :param record_amount: 记录金额。
        :param share_amounts: 各成员的分摊金额。
        :raises ValidationError: 合计不相等。
        """
        total = sum((Decimal(str(item)) for item in share_amounts), Decimal("0"))
        total = total.quantize(CENTS)
        target = Decimal(str(record_amount)).quantize(CENTS)
        if total != target:
            raise ValidationError("分摊金额之和与记录金额不符")

    @staticmethod
    def is_remainder_holder(allocations: Sequence[ShareAllocation]) -> Optional[str]:
        """返回余数归属者的成员标识。

        :param allocations: 分摊结果列表。
        :return: 余数归属者标识，没有余数时返回 ``None``。
        """
        for item in allocations:
            if item.is_remainder_holder:
                return item.member_id
        return None

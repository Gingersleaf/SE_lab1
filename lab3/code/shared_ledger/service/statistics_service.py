"""统计服务。

对应实验二组件图中的统计与预算模块 `StatisticsService`。

本模块是全系统**唯一**实现统计口径的地方（REQ-024、REQ-043）。
实验二组件图里特别强调「统计与预算模块独立且只读」，理由就是这条口径
一旦散落到写入路径上就很容易被改坏；独立成服务后，口径只有一处实现，
分类统计、成员统计、月度趋势、预算进度与结算净额全部复用同一份算法。

口径说明
--------
1. 只有状态为「已通过」的记录参与统计；草稿、待审核、已驳回、已作废
   一律不参与（REQ-024）。
2. 冲正记录以相反方向计入：它的类型与原记录相同、金额相同，但在统计中
   取负号，因此一笔被冲正的金额在分类统计与成员统计中都净额相抵
   （REQ-013、REQ-014）。
3. 与冲正记录配对的原记录在冲正生效后重新纳入统计且取正号。
   这样处理的效果是：**已冲正记录对任何统计总额净贡献恒为零**，
   既满足 REQ-013 的「两条记录净额相抵」，又不会让任何已冲正记录
   单独影响总额。REQ-024 与 REQ-013 在冲正场景下表述存在张力，
   此处按实验二 UI 原型中「冲正条目以 -¥288.00 计入支出」的口径实现。
4. 记录所属月份按记账日期归属，不按审核通过时间归属（REQ-024）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from ..domain.entities import Record, StatResult
from ..domain.enums import RecordStatus
from ..persistence.repositories import RepositoryRegistry
from .base import BaseService, with_denial_log

ZERO = Decimal("0.00")


@dataclass
class CountedEntry:
    """参与统计的一条记录及其方向。

    ``direction`` 为 ``1`` 表示正向计入，为 ``-1`` 表示冲正记录的反向计入。
    """

    record: Record
    direction: int = 1


@dataclass
class LedgerOverview:
    """账本概览页所需的汇总数据。"""

    month: str = ""
    income: Decimal = ZERO
    expense: Decimal = ZERO
    net: Decimal = ZERO
    pending_count: int = 0
    member_count: int = 0
    record_count: int = 0


class StatisticsService(BaseService):
    """统计服务。"""

    def __init__(
        self, repos: RepositoryRegistry, access: Any, logs: Any = None
    ) -> None:
        """初始化服务。

        :param repos: 仓储集合。
        :param access: 权限守卫。
        :param logs: 日志服务。
        """
        super().__init__(repos, access, logs)

    def counted_entries(self, ledger_id: str) -> List[CountedEntry]:
        """返回参与统计的记录及其方向。

        该方法是统计口径的唯一实现，分类统计、成员统计、月度趋势、
        预算进度与结算净额都从这里取数。

        :param ledger_id: 账本标识。
        :return: 参与统计的记录列表。
        """
        records = self.repos.records.list_by_ledger(ledger_id)
        approved_ids = {
            item.record_id
            for item in records
            if item.status is RecordStatus.APPROVED
        }
        entries: List[CountedEntry] = []
        for record in records:
            if record.status is RecordStatus.APPROVED:
                direction = -1 if record.reversal_of_id else 1
                entries.append(CountedEntry(record, direction))
            elif (
                record.status is RecordStatus.REVERSED
                and record.reversed_by_id
                and record.reversed_by_id in approved_ids
            ):
                entries.append(CountedEntry(record, 1))
        return entries

    @with_denial_log
    def overview(
        self, actor_user_id: str, ledger_id: str, month: Optional[str] = None
    ) -> LedgerOverview:
        """返回账本概览页的汇总数据。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :param month: 统计月份，形如 ``2026-11``，默认为当月。
        :return: 概览数据。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        target = month or datetime.now().strftime("%Y-%m")
        overview = LedgerOverview(month=target)
        for entry in self.counted_entries(ledger_id):
            if not entry.record.record_date.isoformat().startswith(target):
                continue
            if entry.record.type.value == "INCOME":
                overview.income += entry.record.amount * entry.direction
            else:
                overview.expense += entry.record.amount * entry.direction
        overview.income = overview.income.quantize(Decimal("0.01"))
        overview.expense = overview.expense.quantize(Decimal("0.01"))
        overview.net = (overview.income - overview.expense).quantize(Decimal("0.01"))
        overview.pending_count = len(
            self.repos.records.list_by_status(ledger_id, RecordStatus.PENDING)
        )
        overview.member_count = self.repos.members.count_active(ledger_id)
        overview.record_count = self.repos.records.count_by_ledger(ledger_id)
        return overview

    @with_denial_log
    def category_statistics(
        self,
        actor_user_id: str,
        ledger_id: str,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> List[StatResult]:
        """按分类汇总收入、支出与净额。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :param start: 起始记账日期。
        :param end: 结束记账日期。
        :return: 分类统计结果列表。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        buckets: Dict[str, StatResult] = {}
        for entry in self.counted_entries(ledger_id):
            record = entry.record
            if not self._in_range(record.record_date, start, end):
                continue
            result = buckets.get(record.category_id)
            if result is None:
                result = StatResult(
                    dimension=record.category_id, label=record.category_name
                )
                buckets[record.category_id] = result
            if record.type.value == "INCOME":
                result.income += record.amount * entry.direction
            else:
                result.expense += record.amount * entry.direction
        return self._finalize(list(buckets.values()))

    @with_denial_log
    def member_statistics(
        self,
        actor_user_id: str,
        ledger_id: str,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> List[StatResult]:
        """按成员汇总收入、支出与净额。

        金额按分摊明细归属，而不是仅按付款人归属（REQ-026）。
        已退出成员的历史金额仍计入其统计结果（REQ-026）。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :param start: 起始记账日期。
        :param end: 结束记账日期。
        :return: 成员统计结果列表。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        buckets: Dict[str, StatResult] = {}
        shares_by_record: Dict[str, List] = {}
        for share in self.repos.shares.list_by_ledger(ledger_id):
            shares_by_record.setdefault(share.record_id, []).append(share)

        for entry in self.counted_entries(ledger_id):
            record = entry.record
            if not self._in_range(record.record_date, start, end):
                continue
            for share in shares_by_record.get(record.record_id, []):
                result = buckets.get(share.member_id)
                if result is None:
                    result = StatResult(
                        dimension=share.member_id, label=share.member_name
                    )
                    buckets[share.member_id] = result
                if record.type.value == "INCOME":
                    result.income += share.amount * entry.direction
                else:
                    result.expense += share.amount * entry.direction
        return self._finalize(list(buckets.values()))

    @with_denial_log
    def monthly_trend(
        self,
        actor_user_id: str,
        ledger_id: str,
        start_month: str = "",
        end_month: str = "",
    ) -> List[StatResult]:
        """按记账日期所在月份汇总收支趋势。

        某月没有已通过记录时该月显示为零值而非缺失（REQ-027）。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :param start_month: 起始月份，形如 ``2026-06``。
        :param end_month: 结束月份，形如 ``2026-11``。
        :return: 月度趋势列表。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        buckets: Dict[str, StatResult] = {}
        for entry in self.counted_entries(ledger_id):
            record = entry.record
            month = record.record_date.strftime("%Y-%m")
            if start_month and month < start_month:
                continue
            if end_month and month > end_month:
                continue
            result = buckets.get(month)
            if result is None:
                result = StatResult(dimension=month, month=month, label=month)
                buckets[month] = result
            if record.type.value == "INCOME":
                result.income += record.amount * entry.direction
            else:
                result.expense += record.amount * entry.direction
        ordered = [buckets[key] for key in sorted(buckets)]
        for month in self._month_range(start_month, end_month):
            if month not in buckets:
                ordered.append(StatResult(dimension=month, month=month, label=month))
        ordered.sort(key=lambda item: item.month)
        return self._finalize(ordered)

    def total_net(self, ledger_id: str) -> Decimal:
        """返回账本在当前口径下的净额。

        结算模块据此校验「成员净额之和等于账本净额」（REQ-030）。

        :param ledger_id: 账本标识。
        :return: 账本净额。
        """
        total = ZERO
        for entry in self.counted_entries(ledger_id):
            total += entry.record.signed_amount * entry.direction
        return total.quantize(Decimal("0.01"))

    @staticmethod
    def _in_range(
        value: date, start: Optional[date], end: Optional[date]
    ) -> bool:
        """判断日期是否落在区间内。

        :param value: 待判断日期。
        :param start: 起始日期。
        :param end: 结束日期。
        :return: 落在区间内时返回 ``True``。
        """
        if start is not None and value < start:
            return False
        if end is not None and value > end:
            return False
        return True

    @staticmethod
    def _finalize(items: List[StatResult]) -> List[StatResult]:
        """统一整理统计结果的小数位与净额。

        :param items: 统计结果列表。
        :return: 整理后的列表。
        """
        for item in items:
            item.income = item.income.quantize(Decimal("0.01"))
            item.expense = item.expense.quantize(Decimal("0.01"))
            item.net = (item.income - item.expense).quantize(Decimal("0.01"))
        return items

    @staticmethod
    def _month_range(start_month: str, end_month: str) -> List[str]:
        """生成月份区间内的所有月份。

        :param start_month: 起始月份。
        :param end_month: 结束月份。
        :return: 月份字符串列表。
        """
        if not start_month or not end_month or start_month > end_month:
            return []
        start = datetime.strptime(start_month, "%Y-%m")
        end = datetime.strptime(end_month, "%Y-%m")
        months: List[str] = []
        current = start
        while current <= end:
            months.append(current.strftime("%Y-%m"))
            year = current.year + (1 if current.month == 12 else 0)
            month = 1 if current.month == 12 else current.month + 1
            current = current.replace(year=year, month=month)
        return months

"""统计口径的单元测试。

覆盖 REQ-024（统计口径）、REQ-025（分类统计）、REQ-026（成员收支统计）、
REQ-027（月度收支趋势）、REQ-043（统计数据的准确性与口径一致性），
并验证 REQ-013 在统计中的净额相抵效果。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from shared_ledger.domain.enums import RecordStatus, RecordType, Role

from tests.base import LedgerTestCase


class StatisticsScopeTest(LedgerTestCase):
    """统计口径的用例。"""

    def test_只有已通过记录计入统计(self) -> None:
        """验证 REQ-024：草稿、待审核、已驳回、已作废、已冲正记录均不计入统计。"""
        # 草稿
        draft = self.create_draft(self.writer, self.draft_input("11.11"))
        # 待审核
        pending = self.create_draft(self.writer, self.draft_input("22.22"))
        self.submit(self.writer, pending)
        # 已驳回
        rejected = self.create_draft(self.writer, self.draft_input("33.33"))
        self.submit(self.writer, rejected)
        self.ctx.audits.reject(
            self.admin.user_id, self.ledger_id, rejected.record_id, "金额有误"
        )
        # 已作废
        voided = self.make_approved(self.writer, "44.44")
        self.ctx.audits.void_record(
            self.admin.user_id, self.ledger_id, voided.record_id, "重复录入"
        )
        # 已通过
        approved = self.make_approved(self.writer, "55.55")
        # 已冲正（原记录被冲正，其冲正记录与原记录净额相抵）
        reversed_pair = self.make_approved(self.writer, "66.66")
        reversal = self.ctx.records.create_reversal(
            self.writer.user_id, self.ledger_id, reversed_pair.record_id
        )
        self.submit(self.writer, reversal)
        self.approve(reversal)

        statuses = {
            item.record_id: item.status
            for item in self.ctx.repos.records.list_by_ledger(self.ledger_id)
        }
        self.assertEqual(statuses[draft.record_id], RecordStatus.DRAFT)
        self.assertEqual(statuses[pending.record_id], RecordStatus.PENDING)
        self.assertEqual(statuses[rejected.record_id], RecordStatus.REJECTED)
        self.assertEqual(statuses[voided.record_id], RecordStatus.VOIDED)
        self.assertEqual(statuses[approved.record_id], RecordStatus.APPROVED)
        self.assertEqual(statuses[reversed_pair.record_id], RecordStatus.REVERSED)

        overview = self.ctx.statistics.overview(self.admin.user_id, self.ledger_id, "2026-11")
        self.assertEqual(overview.expense, Decimal("55.55"))
        self.assertEqual(overview.income, Decimal("0.00"))
        self.assertEqual(overview.net, Decimal("-55.55"))

    def test_记录按记账日期归月而非审核时间(self) -> None:
        """验证 REQ-024：上月末记账、本月审核通过的记录计入上月末的统计。"""
        self.make_approved(
            self.writer,
            "77.00",
            record_date=date(2026, 10, 30),
        )
        october = self.ctx.statistics.overview(self.admin.user_id, self.ledger_id, "2026-10")
        november = self.ctx.statistics.overview(self.admin.user_id, self.ledger_id, "2026-11")
        self.assertEqual(october.expense, Decimal("77.00"))
        self.assertEqual(november.expense, Decimal("0.00"))

    def test_月度趋势按记账日期归月且缺失月份补零(self) -> None:
        """验证 REQ-027：月度趋势按记账日期归属，某月无记录时显示为零值。"""
        self.make_approved(self.writer, "40.00", record_date=date(2026, 10, 5))
        self.make_approved(self.writer, "60.00", record_date=date(2026, 12, 5))
        trend = self.ctx.statistics.monthly_trend(
            self.admin.user_id, self.ledger_id, "2026-10", "2026-12"
        )
        by_month = {item.month: item for item in trend}
        self.assertEqual(by_month["2026-10"].expense, Decimal("40.00"))
        self.assertEqual(by_month["2026-11"].expense, Decimal("0.00"))
        self.assertEqual(by_month["2026-12"].expense, Decimal("60.00"))

    def test_分类统计与成员统计合计一致(self) -> None:
        """验证 REQ-025、REQ-043：分类统计与成员统计的合计与手工汇总一致。"""
        food = self.category("餐饮")
        traffic = self.category("交通")
        self.make_approved(self.writer, "100.00", category=food)
        self.make_approved(self.writer, "30.50", category=traffic)
        self.make_approved(
            self.writer,
            "20.00",
            category=traffic,
            record_type=RecordType.INCOME,
            payer_member_id=self.admin_member.member_id,
            participant_member_ids=[self.admin_member.member_id],
        )

        categories = {
            item.dimension: item
            for item in self.ctx.statistics.category_statistics(
                self.admin.user_id, self.ledger_id
            )
        }
        self.assertEqual(categories[food.category_id].expense, Decimal("100.00"))
        self.assertEqual(categories[traffic.category_id].expense, Decimal("30.50"))
        self.assertEqual(categories[traffic.category_id].income, Decimal("20.00"))
        category_total = sum(
            (item.expense for item in categories.values()), Decimal("0.00")
        )
        self.assertEqual(category_total, Decimal("130.50"))

        members = self.ctx.statistics.member_statistics(
            self.admin.user_id, self.ledger_id
        )
        member_total = sum((item.expense for item in members), Decimal("0.00"))
        self.assertEqual(member_total, category_total)
        self.assertEqual(
            sum((item.net for item in members), Decimal("0.00")),
            self.ctx.statistics.total_net(self.ledger_id),
        )


class MemberStatisticsTest(LedgerTestCase):
    """成员统计归属的用例。"""

    def test_成员统计按分摊明细归属而不是按付款人(self) -> None:
        """验证 REQ-026：成员金额按分摊明细归属，付款人未参与分摊时不计金额。"""
        other = self.ctx.auth.register("writer2", "记账员乙", "123456")
        other_member = self.join(other, Role.WRITER)
        self.make_approved(
            other,
            "90.00",
            payer_member_id=other_member.member_id,
            participant_member_ids=[
                self.admin_member.member_id,
                self.writer_member.member_id,
            ],
        )
        stats = {
            item.dimension: item
            for item in self.ctx.statistics.member_statistics(
                self.admin.user_id, self.ledger_id
            )
        }
        self.assertEqual(stats[self.admin_member.member_id].expense, Decimal("45.00"))
        self.assertEqual(stats[self.writer_member.member_id].expense, Decimal("45.00"))
        self.assertNotIn(other_member.member_id, stats)
        self.assertEqual(
            sum((item.net for item in stats.values()), Decimal("0.00")),
            self.ctx.statistics.total_net(self.ledger_id),
        )

    def test_已退出成员的历史金额仍计入其统计(self) -> None:
        """验证 REQ-026：已退出成员的历史金额仍计入其统计结果。"""
        self.make_approved(
            self.writer,
            "90.00",
            payer_member_id=self.writer_member.member_id,
            participant_member_ids=[
                self.writer_member.member_id,
                self.admin_member.member_id,
            ],
        )
        self.ctx.members.leave_ledger(self.writer.user_id, self.ledger_id)
        stats = {
            item.dimension: item
            for item in self.ctx.statistics.member_statistics(
                self.admin.user_id, self.ledger_id
            )
        }
        self.assertEqual(stats[self.writer_member.member_id].expense, Decimal("45.00"))
        self.assertEqual(stats[self.admin_member.member_id].expense, Decimal("45.00"))


class ReversalStatisticsTest(LedgerTestCase):
    """冲正记录在统计中的净额相抵用例。"""

    def test_冲正生效后分类统计与成员统计净额相抵(self) -> None:
        """验证 REQ-013、REQ-024：冲正生效后原记录与冲正记录在统计中完全抵消。"""
        traffic = self.category("交通")
        original = self.make_approved(
            self.writer,
            "288.00",
            category=traffic,
            payer_member_id=self.writer_member.member_id,
            participant_member_ids=[
                self.writer_member.member_id,
                self.admin_member.member_id,
            ],
        )
        before_categories = {
            item.dimension: item
            for item in self.ctx.statistics.category_statistics(
                self.admin.user_id, self.ledger_id
            )
        }
        self.assertEqual(before_categories[traffic.category_id].expense, Decimal("288.00"))

        reversal = self.ctx.records.create_reversal(
            self.writer.user_id, self.ledger_id, original.record_id
        )
        self.submit(self.writer, reversal)
        self.approve(reversal)

        after_categories = {
            item.dimension: item
            for item in self.ctx.statistics.category_statistics(
                self.admin.user_id, self.ledger_id
            )
        }
        self.assertEqual(after_categories[traffic.category_id].expense, Decimal("0.00"))
        self.assertEqual(after_categories[traffic.category_id].net, Decimal("0.00"))

        after_members = {
            item.dimension: item
            for item in self.ctx.statistics.member_statistics(
                self.admin.user_id, self.ledger_id
            )
        }
        self.assertEqual(
            after_members[self.writer_member.member_id].expense, Decimal("0.00")
        )
        self.assertEqual(
            after_members[self.admin_member.member_id].expense, Decimal("0.00")
        )
        self.assertEqual(self.ctx.statistics.total_net(self.ledger_id), Decimal("0.00"))

    def test_冲正记录审核通过前不参与相抵(self) -> None:
        """验证 REQ-024：冲正记录在审核通过之前不参与相抵，原记录仍按原金额统计。"""
        original = self.make_approved(self.writer, "288.00")
        reversal = self.ctx.records.create_reversal(
            self.writer.user_id, self.ledger_id, original.record_id
        )
        self.submit(self.writer, reversal)
        overview = self.ctx.statistics.overview(self.admin.user_id, self.ledger_id, "2026-11")
        self.assertEqual(overview.expense, Decimal("288.00"))
        self.assertEqual(
            self.ctx.repos.records.find_by_id(original.record_id).status,
            RecordStatus.APPROVED,
        )

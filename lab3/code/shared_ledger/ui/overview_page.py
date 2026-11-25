"""账本概览页面。

包含本月收支四张统计卡、预算执行进度、最近六个月收支趋势、
分类统计与成员收支统计。所有数字都来自统计服务与预算服务，
页面自身不做任何口径判断。
"""

# pylint: disable=attribute-defined-outside-init  # tkinter 控件在多层构建方法中创建，属于构造过程的一部分

# pylint: disable=too-many-instance-attributes  # tkinter 页面需要持有多个控件引用

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import ttk
from typing import List, Tuple

from ..service.budget_service import LEVEL_OVER, LEVEL_WARNING
from .widgets import (
    Card,
    LedgerPage,
    StatCard,
    TrendChart,
    format_amount,
    format_money,
    make_combo,
    make_table,
    month_bounds,
    month_range,
    set_rows,
)

STAT_NOTE = (
    "统计口径：仅统计状态为「已通过」的记录；月份按记账日期归属；"
    "冲正记录以相反方向计入，与原记录净额相抵；已作废与已冲正记录不计入统计。"
)


class OverviewPage(LedgerPage):
    """账本概览页面。"""

    def __init__(self, master: tk.Misc, app: object, **kwargs: object) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, app, **kwargs)
        self.month_var = tk.StringVar(value=month_range(1)[-1])
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def _build(self) -> None:
        """搭建页面结构。"""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self._build_body()

    def _build_header(self) -> None:
        """搭建标题行与统计口径说明。"""
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        title_row = ttk.Frame(header)
        title_row.pack(fill="x")
        ttk.Label(title_row, text="账本概览", style="Title.TLabel").pack(side="left")
        picker = ttk.Frame(title_row)
        picker.pack(side="right")
        ttk.Label(picker, text="统计月份", style="Sub.TLabel").pack(side="left", padx=(0, 8))
        combo = make_combo(picker, month_range(12), width=10)
        combo.set(self.month_var.get())
        combo.bind("<<ComboboxSelected>>", self._on_month_changed)
        combo.pack(side="left")
        self.month_combo = combo
        ttk.Label(
            header,
            text=STAT_NOTE,
            style="Sub.TLabel",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

    def _build_body(self) -> None:
        """搭建统计卡、预算、趋势与两张统计表。"""
        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(2, weight=1)

        cards = ttk.Frame(body)
        cards.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        for index in range(4):
            cards.columnconfigure(index, weight=1, uniform="stat")
        self.income_card = StatCard(cards, "本月收入")
        self.expense_card = StatCard(cards, "本月支出")
        self.net_card = StatCard(cards, "本月结余")
        self.pending_card = StatCard(cards, "待我审核")
        for index, card in enumerate(
            (self.income_card, self.expense_card, self.net_card, self.pending_card)
        ):
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 12) if index < 3 else 0)

        self.budget_card = Card(body, "预算执行进度", "已用金额达到预算 90% 时标橙，超额标红")
        self.budget_card.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        self.budget_area = ttk.Frame(self.budget_card.body)
        self.budget_area.pack(fill="both", expand=True)

        self.trend_card = Card(body, "本月收支趋势", "最近 6 个月")
        self.trend_card.grid(row=1, column=1, sticky="nsew")
        self.trend_chart = TrendChart(self.trend_card.body)
        self.trend_chart.pack(fill="both", expand=True)

        tables = ttk.Frame(body)
        tables.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        tables.columnconfigure(0, weight=1, uniform="tables")
        tables.columnconfigure(1, weight=1, uniform="tables")
        self.category_card = Card(tables, "分类统计", "按已通过记录汇总")
        self.category_card.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.member_card = Card(tables, "成员收支统计", "按分摊明细归属")
        self.member_card.grid(row=0, column=1, sticky="nsew")
        self._build_tables()

    def _build_tables(self) -> None:
        """搭建分类统计与成员统计两张表。"""
        columns = (
            ("name", "名称", 140, "w"),
            ("income", "收入", 110, "e"),
            ("expense", "支出", 110, "e"),
            ("net", "净额", 110, "e"),
        )
        self.category_tree = self._make_table(self.category_card.body, columns)
        self.member_tree = self._make_table(self.member_card.body, columns)

    @staticmethod
    def _make_table(parent: tk.Misc, columns: Tuple) -> ttk.Treeview:
        """在卡片内容区创建一张表格。

        :param parent: 父容器。
        :param columns: 列定义。
        :return: 表格控件。
        """
        holder, tree = make_table(parent, columns, height=4)
        holder.pack(fill="both", expand=True)
        return tree

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def _on_month_changed(self, _event: object = None) -> None:
        """统计月份变化后刷新页面。"""
        self.month_var.set(self.month_combo.get())
        self.refresh()

    def refresh(self) -> None:
        """重新读取统计数据并刷新界面。"""
        month = self.month_var.get()
        start, end = month_bounds(month)
        self._refresh_cards(month)
        self._refresh_budgets(month)
        self._refresh_trend()
        self._refresh_category(start, end)
        self._refresh_member(start, end)

    def _refresh_cards(self, month: str) -> None:
        """刷新四张统计卡。

        :param month: 统计月份。
        """
        overview = self.context.statistics.overview(self.user_id, self.ledger_id, month)
        self.income_card.set_value(format_money(overview.income), "good")
        self.income_card.set_sub(f"账本 {overview.member_count} 位成员 · {overview.record_count} 条记录")
        self.expense_card.set_value(format_money(overview.expense), "normal")
        self.expense_card.set_sub(f"统计月份 {month}")
        tone = "good" if overview.net >= 0 else "bad"
        self.net_card.set_value(format_money(overview.net), tone)
        self.net_card.set_sub("收入 − 支出")
        self.pending_card.set_value(f"{overview.pending_count} 笔", "normal")
        self.pending_card.set_sub("待审核记录需要管理员处理")

    def _refresh_budgets(self, month: str) -> None:
        """刷新预算执行进度。

        :param month: 统计月份。
        """
        for child in self.budget_area.winfo_children():
            child.destroy()
        progress = self.context.budgets.budget_progress(self.user_id, self.ledger_id, month)
        if not progress:
            ttk.Label(self.budget_area, text="尚未设置预算", style="CardMuted.TLabel").pack(
                anchor="w"
            )
            return
        for item in progress:
            self._add_budget_row(item)

    def _add_budget_row(self, item: object) -> None:
        """绘制一条预算进度。

        :param item: 预算进度对象。
        """
        row = ttk.Frame(self.budget_area, style="Card.TFrame")
        row.pack(fill="x", pady=(0, 12))
        head = ttk.Frame(row, style="Card.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text=item.category_name, style="Card.TLabel").pack(side="left")
        ttk.Label(
            head,
            text=f"{format_money(item.used)} / {format_money(item.budget.amount)}",
            style="Card.TLabel",
        ).pack(side="right")
        progress_bar = ttk.Progressbar(
            row, style=self._budget_style(item.level), maximum=100, length=380
        )
        progress_bar.pack(fill="x", pady=(6, 4))
        progress_bar["value"] = min(100.0, max(0.0, item.ratio * 100))
        hint = self._budget_hint(item)
        ttk.Label(row, text=hint, style="CardSub.TLabel").pack(anchor="w")

    @staticmethod
    def _budget_style(level: str) -> str:
        """返回预算进度条样式。

        :param level: 预算水平。
        :return: 样式名。
        """
        if level == LEVEL_OVER:
            return "BudgetOver.Horizontal.TProgressbar"
        if level == LEVEL_WARNING:
            return "BudgetWarn.Horizontal.TProgressbar"
        return "BudgetNormal.Horizontal.TProgressbar"

    @staticmethod
    def _budget_hint(item: object) -> str:
        """返回预算提示语。

        :param item: 预算进度对象。
        :return: 提示文字。
        """
        ratio = int(item.ratio * 100)
        if item.level == LEVEL_OVER:
            return f"已用 {ratio}%，超出预算 {format_money(-item.remaining)}"
        if item.level == LEVEL_WARNING:
            return f"已用 {ratio}%，接近上限，请注意控制支出"
        return f"已用 {ratio}%，剩余 {format_money(item.remaining)}"

    def _refresh_trend(self) -> None:
        """刷新最近六个月的收支趋势。"""
        months = month_range(6)
        trend = self.context.statistics.monthly_trend(
            self.user_id, self.ledger_id, months[0], months[-1]
        )
        points: List[Tuple[str, Decimal, Decimal]] = [
            (item.month, item.income, item.expense) for item in trend if item.month in months
        ]
        self.trend_chart.set_points(points)

    def _refresh_category(self, start: object, end: object) -> None:
        """刷新分类统计表。

        :param start: 起始日期。
        :param end: 结束日期。
        """
        stats = self.context.statistics.category_statistics(
            self.user_id, self.ledger_id, start, end
        )
        rows = []
        for item in stats:
            tone = "income" if item.net > 0 else ("expense" if item.net < 0 else "muted")
            rows.append(
                (
                    (
                        item.label or "（未命名分类）",
                        format_amount(item.income),
                        format_amount(item.expense),
                        format_amount(item.net),
                    ),
                    (tone,),
                )
            )
        set_rows(self.category_tree, rows)

    def _refresh_member(self, start: object, end: object) -> None:
        """刷新成员收支统计表。

        :param start: 起始日期。
        :param end: 结束日期。
        """
        stats = self.context.statistics.member_statistics(
            self.user_id, self.ledger_id, start, end
        )
        rows = []
        for item in stats:
            tone = "income" if item.net > 0 else ("expense" if item.net < 0 else "muted")
            rows.append(
                (
                    (
                        item.label or "（未知成员）",
                        format_amount(item.income),
                        format_amount(item.expense),
                        format_amount(item.net),
                    ),
                    (tone,),
                )
            )
        set_rows(self.member_tree, rows)
        ttk.Label(
            self.member_card.body,
            text="已退出成员的历史金额仍计入其统计，但不参与后续结算。",
            style="CardSub.TLabel",
        ).pack(anchor="w", pady=(8, 0))


__all__ = ["OverviewPage"]

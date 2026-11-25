"""预算设置页面。

列出账本总预算与各分类预算的执行进度，并提供新增或修改预算的表单。
已用金额与进度比例由预算服务按统计口径计算，页面不另算一套。
"""

# pylint: disable=too-many-instance-attributes  # tkinter 页面需要持有多个控件引用

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import ttk
from typing import Dict, List

from ..domain.entities import Category
from ..service.budget_service import LEVEL_OVER, LEVEL_WARNING, BudgetProgress
from .widgets import (
    Card,
    LedgerPage,
    format_money,
    guard,
    make_button,
    make_combo,
    make_entry,
    parse_amount,
    show_info,
)


class BudgetPage(LedgerPage):
    """预算设置页面。"""

    def __init__(self, master: tk.Misc, app: object, **kwargs: object) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, app, **kwargs)
        self.categories: List[Category] = []
        self.category_ids: Dict[str, str] = {}
        self._build()

    def _build(self) -> None:
        """搭建页面结构。"""
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="预算设置", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="已用金额取自统计服务的统一口径；已用达到预算 90% 标橙，超额标红。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        self.card = Card(self, "预算执行进度", "本月")
        self.card.grid(row=1, column=0, sticky="nsew")
        self.list_area = ttk.Frame(self.card.body)
        self.list_area.pack(fill="both", expand=True)

        self.form = Card(self, "新增或修改预算", "同一范围只保留一条预算，重复设置即为修改")
        self.form.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        area = ttk.Frame(self.form.body)
        area.pack(fill="x")
        self.scope_combo = make_combo(area, ("账本总预算",), width=16)
        self.scope_combo.grid(row=0, column=0, sticky="w")
        self.amount_entry = make_entry(area, width=14)
        self.amount_entry.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.ratio_combo = make_combo(area, ("0.9", "0.8", "0.95"), width=6)
        self.ratio_combo.current(0)
        self.ratio_combo.grid(row=0, column=2, sticky="w", padx=(12, 0))
        make_button(area, "保存预算", self._on_save, "Primary.TButton").grid(
            row=0, column=3, sticky="w", padx=(12, 0)
        )
        for index, text in enumerate(("预算范围", "预算金额（元）", "预警比例", "")):
            ttk.Label(area, text=text, style="CardMuted.TLabel").grid(
                row=1, column=index, sticky="w", pady=(4, 0)
            )

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """重新读取预算与分类数据。"""
        self.categories = self.context.categories.list_categories(self.user_id, self.ledger_id)
        self.category_ids = {item.name: item.category_id for item in self.categories}
        options = ("账本总预算",) + tuple(self.category_ids)
        current = self.scope_combo.get()
        self.scope_combo["values"] = options
        self.scope_combo.set(current if current in options else "账本总预算")

        for child in self.list_area.winfo_children():
            child.destroy()
        progress = self.context.budgets.budget_progress(self.user_id, self.ledger_id)
        if not progress:
            ttk.Label(self.list_area, text="尚未设置预算。", style="CardMuted.TLabel").pack(
                anchor="w"
            )
            return
        for item in progress:
            self._add_progress_row(item)

    def _add_progress_row(self, item: BudgetProgress) -> None:
        """绘制一条预算进度。

        :param item: 预算进度对象。
        """
        row = ttk.Frame(self.list_area, style="Card.TFrame")
        row.pack(fill="x", pady=(0, 14))
        head = ttk.Frame(row, style="Card.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text=item.category_name, style="Card.TLabel").pack(side="left")
        ttk.Label(
            head,
            text=f"已用 {format_money(item.used)} / 预算 {format_money(item.budget.amount)}"
            f" · 剩余 {format_money(item.remaining)}",
            style="Card.TLabel",
        ).pack(side="right")
        progress_bar = ttk.Progressbar(
            row, style=self._style_for(item.level), maximum=100, length=520
        )
        progress_bar.pack(fill="x", pady=(6, 4))
        progress_bar["value"] = min(100.0, max(0.0, item.ratio * 100))
        ttk.Label(row, text=self._hint_for(item), style="CardSub.TLabel").pack(anchor="w")

    @staticmethod
    def _style_for(level: str) -> str:
        """返回进度条样式。

        :param level: 预算水平。
        :return: 样式名。
        """
        if level == LEVEL_OVER:
            return "BudgetOver.Horizontal.TProgressbar"
        if level == LEVEL_WARNING:
            return "BudgetWarn.Horizontal.TProgressbar"
        return "BudgetNormal.Horizontal.TProgressbar"

    @staticmethod
    def _hint_for(item: BudgetProgress) -> str:
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

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    @guard
    def _on_save(self) -> None:
        """保存预算。"""
        amount = parse_amount(self.amount_entry.get())
        if amount is None:
            show_info(self, "请填写正确的预算金额。")
            return
        scope = self.scope_combo.get()
        category_id = self.category_ids.get(scope, "") if scope != "账本总预算" else ""
        self.context.budgets.set_budget(
            self.user_id,
            self.ledger_id,
            category_id or None,
            amount,
            Decimal(self.ratio_combo.get()),
        )
        show_info(self, f"「{scope}」的预算已保存。")
        self.refresh()


__all__ = ["BudgetPage"]

"""分类管理页面。

展示账本内的分类、记录条数与本月金额，并提供新建、停用与删除入口。
「已被使用过的分类只能停用不能删除」这条规则由分类服务判定，
页面只负责把服务返回的提示展示出来。
"""

# pylint: disable=too-many-instance-attributes  # tkinter 页面需要持有多个控件引用

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import ttk
from typing import Callable, Dict, List, Tuple

from ..domain.entities import Category
from .widgets import (
    Card,
    LedgerPage,
    bind_row_menu,
    format_amount,
    guard,
    make_button,
    make_entry,
    make_table,
    month_bounds,
    set_rows,
    show_info,
)

CATEGORY_COLUMNS = (
    ("name", "分类名称", 160, "w"),
    ("source", "来源", 90, "center"),
    ("status", "状态", 80, "center"),
    ("count", "记录条数", 90, "e"),
    ("income", "本月收入", 110, "e"),
    ("expense", "本月支出", 110, "e"),
    ("action", "操作", 140, "w"),
)


class CategoryPage(LedgerPage):
    """分类管理页面。"""

    def __init__(self, master: tk.Misc, app: object, **kwargs: object) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, app, **kwargs)
        self.categories: List[Category] = []
        self.month_amounts: Dict[str, Tuple[Decimal, Decimal]] = {}
        self._build()

    def _build(self) -> None:
        """搭建页面结构。"""
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="分类管理", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="停用后该分类不能再被新记录选用，历史记录仍显示原分类名称；"
            "已被记录使用的分类只能停用，不能删除。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        self.card = Card(self)
        self.card.grid(row=1, column=0, sticky="nsew")
        holder, self.tree = make_table(self.card.body, CATEGORY_COLUMNS, height=9)
        holder.pack(fill="both", expand=True)
        bind_row_menu(self.tree, "action", self._row_actions)

        create = Card(self, "新建分类", "自建分类最多 12 个字符，名称不可重复")
        create.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        area = ttk.Frame(create.body)
        area.pack(fill="x")
        self.name_entry = make_entry(area, width=18)
        self.name_entry.grid(row=0, column=0, sticky="w")
        make_button(area, "新建", self._on_create, "Primary.TButton").grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        ttk.Label(
            create.body,
            text="系统默认分类随账本创建自动铺好，删除后不可恢复。",
            style="CardSub.TLabel",
        ).pack(anchor="w", pady=(8, 0))

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """重新读取分类数据。"""
        self.categories = self.context.categories.list_categories(self.user_id, self.ledger_id)
        self._load_month_amounts()
        set_rows(self.tree, [self._row_for(item) for item in self.categories])

    def _load_month_amounts(self) -> None:
        """读取本月各分类的收支金额。"""
        start, end = month_bounds(date.today().strftime("%Y-%m"))
        stats = self.context.statistics.category_statistics(
            self.user_id, self.ledger_id, start, end
        )
        self.month_amounts = {item.dimension: (item.income, item.expense) for item in stats}

    def _row_for(self, category: Category) -> tuple:
        """把分类实体转换成表格行。

        :param category: 分类实体。
        :return: ``(各列取值, 行标签)``。
        """
        income, expense = self.month_amounts.get(
            category.category_id, (Decimal("0.00"), Decimal("0.00"))
        )
        actions = []
        if category.status.value == "ENABLED":
            actions.append("停用")
        if category.record_count == 0:
            actions.append("删除")
        values = (
            category.name,
            "默认" if category.is_default else "自建",
            category.status.display_name,
            str(category.record_count),
            format_amount(income),
            format_amount(expense),
            " · ".join(actions) if actions else "—",
        )
        tags = ("muted",) if category.status.value == "DISABLED" else ()
        return values, tags

    def _row_actions(self, row: str) -> List[Tuple[str, Callable[[], None]]]:
        """返回某一行分类可执行的操作。

        :param row: 表格行标识。
        :return: ``(菜单文字, 回调)`` 列表。
        """
        category = self._category_for(row)
        if category is None:
            return []
        actions: List[Tuple[str, Callable[[], None]]] = []
        if category.status.value == "ENABLED":
            actions.append(("停用分类", lambda: self._disable(category)))
        if category.record_count == 0:
            actions.append(("删除分类", lambda: self._delete(category)))
        return actions

    def _category_for(self, row: str) -> object:
        """按表格行标识找到对应的分类。

        :param row: 表格行标识。
        :return: 分类实体；找不到时返回 ``None``。
        """
        values = self.tree.item(row, "values")
        if not values:
            return None
        name = str(values[0])
        for item in self.categories:
            if item.name == name:
                return item
        return None

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    @guard
    def _on_create(self) -> None:
        """新建分类。"""
        name = self.name_entry.get().strip()
        if not name:
            show_info(self, "请填写分类名称。")
            return
        self.context.categories.create_category(self.user_id, self.ledger_id, name)
        self.name_entry.delete(0, "end")
        show_info(self, f"分类「{name}」已创建。")
        self.refresh()

    @guard
    def _disable(self, category: Category) -> None:
        """停用分类。

        :param category: 分类实体。
        """
        self.context.categories.disable_category(self.user_id, self.ledger_id, category.category_id)
        show_info(self, f"分类「{category.name}」已停用。")
        self.refresh()

    @guard
    def _delete(self, category: Category) -> None:
        """删除分类。

        :param category: 分类实体。
        """
        self.context.categories.delete_category(self.user_id, self.ledger_id, category.category_id)
        show_info(self, f"分类「{category.name}」已删除。")
        self.refresh()


__all__ = ["CategoryPage"]

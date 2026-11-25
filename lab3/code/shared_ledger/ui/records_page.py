"""收支记录列表页面。

提供多条件组合筛选、分页浏览与记录入口。查询条件全部通过记录服务的
``query_records`` 提交，界面层不写 SQL、不自己判断统计口径。
"""

# pylint: disable=attribute-defined-outside-init  # tkinter 控件在多层构建方法中创建，属于构造过程的一部分

# pylint: disable=too-many-instance-attributes  # tkinter 页面需要持有多个控件引用
# pylint: disable=too-many-locals  # 筛选条件较多，集中在一个方法里更清晰

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import ttk
from typing import Callable, Dict, Optional

from ..domain.entities import Record
from ..domain.enums import RecordStatus, RecordType
from ..persistence.repositories import RecordFilter
from .widgets import (
    Card,
    LedgerPage,
    format_amount,
    make_button,
    make_combo,
    make_entry,
    make_table,
    parse_amount,
    parse_date,
    set_rows,
)

TYPE_LABELS = ("全部", "收入", "支出")
STATUS_LABELS = ("全部",) + tuple(item.display_name for item in RecordStatus)
COLUMNS = (
    ("record_id", "记录号", 150, "w"),
    ("record_date", "记账日期", 96, "center"),
    ("type", "类型", 64, "center"),
    ("amount", "金额", 110, "e"),
    ("category", "分类", 90, "w"),
    ("payer", "付款人", 92, "w"),
    ("status", "状态", 150, "w"),
    ("note", "备注", 180, "w"),
)


class RecordsPage(LedgerPage):
    """收支记录列表页面。"""

    def __init__(self, master: tk.Misc, app: object, **kwargs: object) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, app, **kwargs)
        self.page_number = 1
        self.page_size = 15
        self.total = 0
        self.member_names: Dict[str, str] = {}
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def _build(self) -> None:
        """搭建筛选区、结果表与分页条。"""
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self._build_filters()
        self._build_result()
        self._build_pager()

    def _build_filters(self) -> None:
        """搭建筛选区。"""
        card = Card(self, "筛选条件", "各条件之间是「并且」关系，翻页时条件保持不变")
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        area = ttk.Frame(card.body)
        area.pack(fill="x")

        first = ttk.Frame(area)
        first.pack(fill="x", pady=(0, 8))
        self.type_combo = self._add_field(
            first, "收支类型", lambda box: make_combo(box, TYPE_LABELS, width=8)
        )
        self.category_combo = self._add_field(
            first, "分类", lambda box: make_combo(box, ("全部",), width=12)
        )
        self.member_combo = self._add_field(
            first, "成员", lambda box: make_combo(box, ("全部",), width=12)
        )
        self.status_combo = self._add_field(
            first, "状态", lambda box: make_combo(box, STATUS_LABELS, width=10)
        )

        second = ttk.Frame(area)
        second.pack(fill="x")
        self.date_from_entry = self._add_field(
            second, "记账日期从", lambda box: make_entry(box, width=12)
        )
        self.date_to_entry = self._add_field(
            second, "记账日期至", lambda box: make_entry(box, width=12)
        )
        self.amount_min_entry = self._add_field(
            second, "金额下限", lambda box: make_entry(box, width=10)
        )
        self.amount_max_entry = self._add_field(
            second, "金额上限", lambda box: make_entry(box, width=10)
        )
        self.keyword_entry = self._add_field(
            second, "备注关键字", lambda box: make_entry(box, width=14)
        )

        buttons = ttk.Frame(area)
        buttons.pack(fill="x", pady=(10, 0))
        make_button(buttons, "查询", self._on_query, "Primary.TButton").pack(side="left")
        make_button(buttons, "重置", self._on_reset).pack(side="left", padx=(8, 0))
        make_button(buttons, "查看详情", self._on_detail).pack(side="left", padx=(8, 0))
        make_button(buttons, "记一笔", self._on_create).pack(side="left", padx=(8, 0))
        ttk.Label(
            area,
            text="提示：已作废与已驳回记录不计入统计；已冲正记录与冲正记录净额相抵。",
            style="CardSub.TLabel",
        ).pack(anchor="w", pady=(10, 0))

    @staticmethod
    def _add_field(parent: tk.Misc, label: str, factory: Callable) -> ttk.Widget:
        """在筛选区添加一个「标签 + 控件」组合。

        :param parent: 父容器。
        :param label: 标签文字。
        :param factory: 创建控件的工厂函数，参数为控件的父容器。
        :return: 创建出来的控件。
        """
        holder = ttk.Frame(parent)
        holder.pack(side="left", padx=(0, 14))
        ttk.Label(holder, text=label, style="Card.TLabel").grid(row=0, column=0, sticky="w")
        widget = factory(holder)
        widget.grid(row=1, column=0, sticky="w", pady=(4, 0))
        return widget

    def _build_result(self) -> None:
        """搭建结果表格。"""
        card = Card(self)
        card.grid(row=1, column=0, sticky="nsew")
        holder, self.tree = make_table(card.body, COLUMNS, height=11)
        holder.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _event: self._on_detail())

    def _build_pager(self) -> None:
        """搭建分页条。"""
        pager = ttk.Frame(self)
        pager.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.page_label = ttk.Label(pager, text="", style="Sub.TLabel")
        self.page_label.pack(side="left")
        make_button(pager, "上一页", lambda: self._turn_page(-1)).pack(side="right")
        self.next_button = make_button(pager, "下一页", lambda: self._turn_page(1))
        self.next_button.pack(side="right", padx=(8, 0))
        self.size_combo = make_combo(pager, ("15", "25", "50"), width=6)
        self.size_combo.set(str(self.page_size))
        self.size_combo.bind("<<ComboboxSelected>>", self._on_size_changed)
        self.size_combo.pack(side="right", padx=(0, 12))
        ttk.Label(pager, text="每页条数", style="Sub.TLabel").pack(side="right", padx=(0, 6))

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _on_query(self) -> None:
        """按当前筛选条件重新查询。"""
        self.page_number = 1
        self.refresh()

    def _on_reset(self) -> None:
        """清空筛选条件。"""
        self.type_combo.current(0)
        self.status_combo.current(0)
        self.category_combo.current(0)
        self.member_combo.current(0)
        for entry in (
            self.date_from_entry,
            self.date_to_entry,
            self.amount_min_entry,
            self.amount_max_entry,
            self.keyword_entry,
        ):
            entry.delete(0, "end")
        self.page_number = 1
        self.refresh()

    def _on_size_changed(self, _event: object = None) -> None:
        """每页条数变化后回到第一页重新查询。"""
        self.page_size = int(self.size_combo.get())
        self.page_number = 1
        self.refresh()

    def _turn_page(self, step: int) -> None:
        """翻页。

        :param step: 页码增量。
        """
        self.page_number = max(1, self.page_number + step)
        self.refresh()

    def _on_detail(self) -> None:
        """打开选中记录的详情页。"""
        record_id = self._selected_id()
        if record_id:
            self.app.open_record_detail(record_id)

    def _on_create(self) -> None:
        """打开新建记录的表单页。"""
        self.app.open_record_form()

    def _selected_id(self) -> str:
        """返回当前选中行的记录号。"""
        selection = self.tree.selection()
        if not selection:
            return ""
        values = self.tree.item(selection[0], "values")
        return str(values[0]) if values else ""

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """重新读取记录列表。"""
        self._reload_options()
        criteria = self._build_criteria()
        page = self.context.records.query_records(self.user_id, self.ledger_id, criteria)
        self.total = page.total
        rows = [self._row_for(item) for item in page.items]
        set_rows(self.tree, rows)
        self.page_label.configure(
            text=f"共 {page.total} 条记录 · 第 {page.page} / {max(1, page.page_count)} 页"
        )

    def _reload_options(self) -> None:
        """刷新分类与成员下拉框的可选项。"""
        categories = self.context.categories.list_categories(self.user_id, self.ledger_id)
        current = self.category_combo.get()
        self.category_combo["values"] = ("全部",) + tuple(item.name for item in categories)
        self.category_combo.set(current if current in self.category_combo["values"] else "全部")

        members = self.context.members.list_members(self.user_id, self.ledger_id)
        self.member_names = {item.member.member_id: item.member.display_name for item in members}
        names = tuple(item.member.display_name for item in members)
        current_member = self.member_combo.get()
        self.member_combo["values"] = ("全部",) + names
        self.member_combo.set(current_member if current_member in names else "全部")

    def _build_criteria(self) -> RecordFilter:
        """把界面上的筛选条件组装成查询条件。"""
        return RecordFilter(
            record_type=self._selected_type(),
            category_id=self._selected_category(),
            member_id=self._selected_member(),
            status=self._selected_status(),
            date_from=parse_date(self.date_from_entry.get()),
            date_to=parse_date(self.date_to_entry.get()),
            amount_min=self._selected_amount(self.amount_min_entry),
            amount_max=self._selected_amount(self.amount_max_entry),
            keyword=self.keyword_entry.get().strip(),
            page=self.page_number,
            page_size=self.page_size,
        )

    def _selected_type(self) -> Optional[RecordType]:
        """返回选中的收支类型。"""
        label = self.type_combo.get()
        if label == "收入":
            return RecordType.INCOME
        if label == "支出":
            return RecordType.EXPENSE
        return None

    def _selected_category(self) -> str:
        """返回选中的分类标识。"""
        name = self.category_combo.get()
        if name in ("", "全部"):
            return ""
        categories = self.context.categories.list_categories(self.user_id, self.ledger_id)
        for item in categories:
            if item.name == name:
                return item.category_id
        return ""

    def _selected_member(self) -> str:
        """返回选中的成员标识。"""
        name = self.member_combo.get()
        if name in ("", "全部"):
            return ""
        members = self.context.members.list_members(self.user_id, self.ledger_id)
        for item in members:
            if item.member.display_name == name:
                return item.member.member_id
        return ""

    def _selected_status(self) -> Optional[RecordStatus]:
        """返回选中的记录状态。"""
        label = self.status_combo.get()
        for item in RecordStatus:
            if item.display_name == label:
                return item
        return None

    @staticmethod
    def _selected_amount(entry: ttk.Entry) -> Optional[Decimal]:
        """返回金额区间输入框中的数值。

        :param entry: 输入框。
        :return: 数值；未填写或非法时返回 ``None``。
        """
        return parse_amount(entry.get())

    def _row_for(self, record: Record) -> tuple:
        """把记录实体转换成表格行。

        :param record: 记录实体。
        :return: ``(各列取值, 行标签)``。
        """
        status_text = record.status.display_name
        if record.status is RecordStatus.VOIDED:
            status_text = "已作废（不计入统计）"
        elif record.status is RecordStatus.REVERSED:
            status_text = "已冲正（与冲正记录相抵）"
        elif not record.status.counted_in_statistics:
            status_text = f"{status_text}（未计入统计）"
        payer = record.payer_name or self.member_names.get(record.payer_id, "—")
        values = (
            record.record_id,
            record.record_date.isoformat(),
            record.type.display_name,
            format_amount(record.amount),
            record.category_name or "—",
            payer,
            status_text,
            record.note or "—",
        )
        tags = ("income",) if record.type is RecordType.INCOME else ("expense",)
        if not record.status.counted_in_statistics:
            tags = ("muted",)
        return values, tags


__all__ = ["RecordsPage"]

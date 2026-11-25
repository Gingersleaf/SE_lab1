"""操作日志页面。

按操作类型、操作人与时间范围筛选日志，并展示时间、操作人、操作类型、
操作对象、关键参数与日志编号。日志只增不改不删，页面不提供任何
修改或删除入口。
"""

# pylint: disable=too-many-instance-attributes  # tkinter 页面需要持有多个控件引用

from __future__ import annotations

import tkinter as tk
from datetime import datetime, time
from tkinter import ttk
from typing import Dict, Optional

from ..domain.entities import OperationLog
from ..domain.enums import LogActionType
from ..domain.errors import LedgerError
from .widgets import (
    Card,
    LedgerPage,
    make_button,
    make_combo,
    make_entry,
    make_table,
    parse_date,
    set_rows,
)

ACTION_LABELS = ("全部",) + tuple(item.display_name for item in LogActionType)
COLUMNS = (
    ("time", "发生时间", 150, "center"),
    ("actor", "操作人", 110, "w"),
    ("action", "操作类型", 120, "w"),
    ("target", "操作对象", 180, "w"),
    ("params", "关键参数", 320, "w"),
    ("log_id", "日志编号", 160, "w"),
)


class LogPage(LedgerPage):
    """操作日志页面。"""

    def __init__(self, master: tk.Misc, app: object, **kwargs: object) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, app, **kwargs)
        self.page_number = 1
        self.page_size = 30
        self.total = 0
        self.member_names: Dict[str, str] = {}
        self._build()

    def _build(self) -> None:
        """搭建页面结构。"""
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="操作日志", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="日志只增不改不删，任何角色都不能修改或删除；越权被拒绝时同样留痕。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        card = Card(self, "筛选条件", "管理员可查询全账本日志，记账成员只能查询与自己相关的日志")
        card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        area = ttk.Frame(card.body)
        area.pack(fill="x")
        self.action_combo = make_combo(area, ACTION_LABELS, width=14)
        self.action_combo.grid(row=0, column=0, sticky="w")
        self.actor_combo = make_combo(area, ("全部",), width=14)
        self.actor_combo.grid(row=0, column=1, sticky="w", padx=(14, 0))
        self.start_entry = make_entry(area, width=12)
        self.start_entry.grid(row=0, column=2, sticky="w", padx=(14, 0))
        self.end_entry = make_entry(area, width=12)
        self.end_entry.grid(row=0, column=3, sticky="w", padx=(14, 0))
        make_button(area, "查询", self._on_query, "Primary.TButton").grid(
            row=0, column=4, sticky="w", padx=(14, 0)
        )
        make_button(area, "重置", self._on_reset).grid(row=0, column=5, sticky="w", padx=(8, 0))
        for index, text in enumerate(("操作类型", "操作人", "开始时间", "结束时间", "", "")):
            ttk.Label(area, text=text, style="CardMuted.TLabel").grid(
                row=1, column=index, sticky="w", pady=(4, 0)
            )

        result = Card(self)
        result.grid(row=2, column=0, sticky="nsew")
        holder, self.tree = make_table(result.body, COLUMNS, height=11)
        holder.pack(fill="both", expand=True)

        pager = ttk.Frame(self)
        pager.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.page_label = ttk.Label(pager, text="", style="Sub.TLabel")
        self.page_label.pack(side="left")
        make_button(pager, "上一页", lambda: self._turn_page(-1)).pack(side="right")
        make_button(pager, "下一页", lambda: self._turn_page(1)).pack(side="right", padx=(8, 0))

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _on_query(self) -> None:
        """按当前条件查询日志。"""
        self.page_number = 1
        self.refresh()

    def _on_reset(self) -> None:
        """清空筛选条件。"""
        self.action_combo.current(0)
        self.actor_combo.current(0)
        self.start_entry.delete(0, "end")
        self.end_entry.delete(0, "end")
        self.page_number = 1
        self.refresh()

    def _turn_page(self, step: int) -> None:
        """翻页。

        :param step: 页码增量。
        """
        self.page_number = max(1, self.page_number + step)
        self.refresh()

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """重新读取操作日志。"""
        self._reload_actors()
        try:
            page = self.context.logs.query(
                self.user_id,
                self.ledger_id,
                action=self._selected_action(),
                actor_member_id=self._selected_actor(),
                start=self._parse_datetime(self.start_entry.get(), False),
                end=self._parse_datetime(self.end_entry.get(), True),
                page=self.page_number,
                page_size=self.page_size,
            )
        except LedgerError as exc:
            set_rows(self.tree, [])
            self.page_label.configure(text=exc.message)
            return
        self.total = page.total
        set_rows(self.tree, [self._row_for(item) for item in page.items])
        self.page_label.configure(
            text=f"共 {page.total} 条日志 · 第 {page.page} / {max(1, page.page_count)} 页"
        )

    def _reload_actors(self) -> None:
        """刷新操作人下拉框。"""
        members = self.context.members.list_members(self.user_id, self.ledger_id)
        self.member_names = {item.member.member_id: item.member.display_name for item in members}
        names = tuple(item.member.display_name for item in members)
        current = self.actor_combo.get()
        self.actor_combo["values"] = ("全部",) + names
        self.actor_combo.set(current if current in names else "全部")

    def _selected_action(self) -> Optional[LogActionType]:
        """返回选中的操作类型。"""
        label = self.action_combo.get()
        for item in LogActionType:
            if item.display_name == label:
                return item
        return None

    def _selected_actor(self) -> str:
        """返回选中的操作人标识。"""
        name = self.actor_combo.get()
        if name in ("", "全部"):
            return ""
        members = self.context.members.list_members(self.user_id, self.ledger_id)
        for item in members:
            if item.member.display_name == name:
                return item.member.member_id
        return ""

    @staticmethod
    def _parse_datetime(text: str, end_of_day: bool) -> Optional[datetime]:
        """解析时间范围输入。

        :param text: 输入文本，格式为 ``YYYY-MM-DD``。
        :param end_of_day: 是否取当天末尾时刻。
        :return: 时间点；输入为空或非法时返回 ``None``。
        """
        day = parse_date(text)
        if day is None:
            return None
        return datetime.combine(day, time.max if end_of_day else time.min)

    def _row_for(self, log: OperationLog) -> tuple:
        """把日志实体转换成表格行。

        :param log: 日志实体。
        :return: ``(各列取值, 行标签)``。
        """
        actor = log.actor_name or self.member_names.get(log.actor_id, "系统")
        values = (
            log.occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
            actor,
            log.action.display_name,
            f"{log.target_type or '—'} · {log.target_id or '—'}",
            log.params or "—",
            log.log_id,
        )
        tags = ("muted",) if log.action is LogActionType.ACCESS_DENIED else ()
        return values, tags


__all__ = ["LogPage"]

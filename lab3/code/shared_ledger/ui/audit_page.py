"""待审核记录页面。

按行给出通过、驳回与作废三个入口，驳回与作废都会弹出原因输入框，
原因会随操作写入记录状态历史与操作日志。
"""

# pylint: disable=too-many-instance-attributes  # tkinter 页面需要持有多个控件引用

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..domain.entities import Record
from ..domain.errors import LedgerError
from .widgets import (
    Card,
    LedgerPage,
    ScrollFrame,
    ask_reason,
    format_money,
    guard,
    make_button,
    show_info,
)


class AuditPage(LedgerPage):
    """待审核记录页面。"""

    def __init__(self, master: tk.Misc, app: object, **kwargs: object) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, app, **kwargs)
        self._build()

    def _build(self) -> None:
        """搭建页面结构。"""
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="待审核记录", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="审核通过后记录才计入统计；驳回与作废必须填写原因，原因写入状态历史与操作日志。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(6, 0))
        make_button(header, "刷新", self.refresh).pack(anchor="e", pady=(6, 0))

        card = Card(self)
        card.grid(row=1, column=0, sticky="nsew")
        self.scroller = ScrollFrame(card.body)
        self.scroller.pack(fill="both", expand=True)
        self.list_area = self.scroller.inner
        self.hint_label = ttk.Label(card.body, text="", style="CardMuted.TLabel")
        self.hint_label.pack(anchor="w", pady=(8, 0))

    def refresh(self) -> None:
        """重新读取待审核记录。"""
        for child in self.list_area.winfo_children():
            child.destroy()
        try:
            records = self.context.audits.list_pending(self.user_id, self.ledger_id)
        except LedgerError as exc:
            self.hint_label.configure(text=exc.message)
            return
        self.hint_label.configure(text=f"共 {len(records)} 条待审核记录")
        if not records:
            ttk.Label(self.list_area, text="当前没有待审核记录。", style="CardMuted.TLabel").pack(
                anchor="w", pady=8
            )
            return
        for record in records:
            self._add_row(record)

    def _add_row(self, record: Record) -> None:
        """添加一条待审核记录。

        :param record: 记录实体。
        """
        row = ttk.Frame(self.list_area, style="Card.TFrame")
        row.pack(fill="x", pady=(0, 8))
        info = ttk.Frame(row, style="Card.TFrame")
        info.pack(side="left", fill="x", expand=True)
        first = ttk.Frame(info, style="Card.TFrame")
        first.pack(fill="x")
        ttk.Label(first, text=record.record_id, style="Card.TLabel").pack(side="left")
        ttk.Label(
            first,
            text=f"{record.type.display_name} {format_money(record.amount)}",
            style="Card.TLabel",
        ).pack(side="left", padx=(14, 0))
        ttk.Label(
            first,
            text=f"{record.record_date.isoformat()} · {record.category_name or '—'}",
            style="CardMuted.TLabel",
        ).pack(side="left", padx=(14, 0))
        ttk.Label(
            info,
            text=f"录入人 {record.creator_name or '—'} · 付款人 {record.payer_name or '—'}"
            f" · 备注 {record.note or '—'}",
            style="CardMuted.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        actions = ttk.Frame(row, style="Card.TFrame")
        actions.pack(side="right")
        make_button(actions, "通过", lambda item=record: self._approve(item)).pack(
            side="left", padx=(0, 6)
        )
        make_button(actions, "驳回", lambda item=record: self._reject(item)).pack(
            side="left", padx=(0, 6)
        )
        make_button(actions, "作废", lambda item=record: self._void(item), "Danger.TButton").pack(
            side="left"
        )
        make_button(
            actions, "详情", lambda item=record: self._open_detail(item), "Ghost.TButton"
        ).pack(side="left", padx=(6, 0))

    @guard
    def _approve(self, record: Record) -> None:
        """审核通过一条记录。

        :param record: 记录实体。
        """
        self.context.audits.approve(self.user_id, self.ledger_id, record.record_id)
        show_info(self, f"{record.record_id} 已审核通过并计入统计。")
        self.refresh()

    @guard
    def _reject(self, record: Record) -> None:
        """驳回一条记录。

        :param record: 记录实体。
        """
        reason = ask_reason(self, "驳回记录", "请填写驳回原因：")
        if not reason:
            return
        self.context.audits.reject(self.user_id, self.ledger_id, record.record_id, reason)
        show_info(self, f"{record.record_id} 已驳回。")
        self.refresh()

    @guard
    def _void(self, record: Record) -> None:
        """作废一条记录。

        :param record: 记录实体。
        """
        reason = ask_reason(self, "作废记录", "请填写作废原因：")
        if not reason:
            return
        self.context.audits.void_record(self.user_id, self.ledger_id, record.record_id, reason)
        show_info(self, f"{record.record_id} 已作废。")
        self.refresh()

    def _open_detail(self, record: Record) -> None:
        """打开记录详情。

        :param record: 记录实体。
        """
        self.app.open_record_detail(record.record_id)


__all__ = ["AuditPage"]

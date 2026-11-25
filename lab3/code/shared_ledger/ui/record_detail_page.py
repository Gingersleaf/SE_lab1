"""记录详情页面。

展示记录基本信息、分摊明细、状态历史与冲正关联，并按当前状态
动态给出可执行的操作。操作按钮的名称来自状态机组件给出的可用动作列表，
页面不自行判断哪些操作在当前状态下合法。
"""

# pylint: disable=attribute-defined-outside-init  # tkinter 控件在多层构建方法中创建，属于构造过程的一部分

# pylint: disable=too-many-instance-attributes  # tkinter 页面需要持有多个控件引用

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, Optional

from ..domain.entities import Record
from ..domain.enums import RecordStatus
from ..service.record_service import RecordDetail
from . import theme
from .widgets import (
    Card,
    LedgerPage,
    ask_reason,
    format_money,
    guard,
    make_button,
    make_table,
    set_rows,
    show_info,
)

SHARE_COLUMNS = (
    ("member", "成员", 160, "w"),
    ("amount", "分摊金额", 120, "e"),
    ("note", "说明", 200, "w"),
)


class RecordDetailPage(LedgerPage):
    """记录详情页面。"""

    def __init__(self, master: tk.Misc, app: object, **kwargs: object) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, app, **kwargs)
        self.record_id = ""
        self.detail: Optional[RecordDetail] = None
        self._build()

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def _build(self) -> None:
        """搭建页面结构。"""
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self._build_body()

    def _build_header(self) -> None:
        """搭建标题行。"""
        header = ttk.Frame(self)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.title_label = ttk.Label(header, text="记录详情", style="Title.TLabel")
        self.title_label.pack(anchor="w")
        self.subtitle_label = ttk.Label(header, text="", style="Sub.TLabel")
        self.subtitle_label.pack(anchor="w", pady=(6, 0))
        make_button(header, "返回记录列表", lambda: self.app.show_page("records")).pack(
            anchor="e", pady=(6, 0)
        )

    def _build_body(self) -> None:
        """搭建左右两栏内容。"""
        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        right = ttk.Frame(self)
        right.grid(row=1, column=1, sticky="nsew")

        self.basic_card = Card(left, "基本信息")
        self.basic_card.pack(fill="x")
        self.basic_area = ttk.Frame(self.basic_card.body)
        self.basic_area.pack(fill="x")

        self.share_card = Card(left, "分摊明细", "分摊在记录创建时确定，成员增减不影响已有记录")
        self.share_card.pack(fill="x", pady=(14, 0))
        holder, self.share_tree = make_table(self.share_card.body, SHARE_COLUMNS, height=3)
        holder.pack(fill="both", expand=True)

        self.reversal_card = Card(left, "冲正关联", "冲正记录与原记录成对出现，在统计中净额相抵")
        self.reversal_card.pack(fill="x", pady=(14, 0))
        self.reversal_area = ttk.Frame(self.reversal_card.body)
        self.reversal_area.pack(fill="x")

        self.action_card = Card(right, "可用操作", "按记录当前状态动态显示")
        self.action_card.pack(fill="x")
        self.action_area = ttk.Frame(self.action_card.body)
        self.action_area.pack(fill="x")

        self.trace_card = Card(right, "状态历史", "驳回原因与作废原因可追溯")
        self.trace_card.pack(fill="both", expand=True, pady=(14, 0))
        self.trace_area = ttk.Frame(self.trace_card.body)
        self.trace_area.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # 数据填充
    # ------------------------------------------------------------------
    def open_detail(self, record_id: str) -> None:
        """打开指定记录的详情。

        :param record_id: 记录标识。
        """
        self.record_id = record_id
        self.refresh()

    def refresh(self) -> None:
        """重新读取记录详情并刷新界面。"""
        if not self.record_id:
            return
        detail = self.context.records.get_detail(self.user_id, self.ledger_id, self.record_id)
        self.detail = detail
        record = detail.record
        self.title_label.configure(text=f"{record.record_id} · {record.type.display_name}")
        self.subtitle_label.configure(
            text=f"状态：{record.status.display_name}；录入人 {record.creator_name or '—'}"
        )
        self._fill_basic(record)
        self._fill_shares(detail)
        self._fill_reversal(detail)
        self._fill_actions(detail)
        self._fill_traces(detail)

    def _fill_basic(self, record: Record) -> None:
        """填充基本信息卡片。

        :param record: 记录实体。
        """
        for child in self.basic_area.winfo_children():
            child.destroy()
        rows = (
            ("记录号", record.record_id),
            ("收支类型", record.type.display_name),
            ("金额", format_money(record.amount)),
            ("分类", record.category_name or "—"),
            ("记账日期", record.record_date.isoformat()),
            ("付款人", record.payer_name or "—"),
            ("录入人", record.creator_name or "—"),
            ("备注", record.note or "—"),
            ("状态", record.status.display_name),
            ("版本号", str(record.version)),
            ("提交时间", record.submitted_at.strftime("%Y-%m-%d %H:%M:%S")
             if record.submitted_at else "—"),
            ("审核时间", record.reviewed_at.strftime("%Y-%m-%d %H:%M:%S")
             if record.reviewed_at else "—"),
        )
        for label, value in rows:
            row = ttk.Frame(self.basic_area, style="Card.TFrame")
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, style="CardMuted.TLabel").pack(side="left")
            ttk.Label(row, text=value, style="Card.TLabel").pack(side="right")

    def _fill_shares(self, detail: RecordDetail) -> None:
        """填充分摊明细表。

        :param detail: 记录详情。
        """
        rows = []
        for share in detail.shares:
            note = "余数归属者" if share.is_remainder_holder else ""
            rows.append(((share.member_name or "—", format_money(share.amount), note), ()))
        set_rows(self.share_tree, rows)

    def _fill_reversal(self, detail: RecordDetail) -> None:
        """填充冲正关联信息。

        :param detail: 记录详情。
        """
        for child in self.reversal_area.winfo_children():
            child.destroy()
        if detail.reversal is None and detail.reversed_by is None:
            ttk.Label(self.reversal_area, text="该记录没有关联的冲正记录。",
                      style="CardMuted.TLabel").pack(anchor="w")
            return
        for label, record in (("冲正记录", detail.reversal), ("被冲正的原记录", detail.reversed_by)):
            if record is None:
                continue
            row = ttk.Frame(self.reversal_area, style="Card.TFrame")
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, style="CardMuted.TLabel").pack(side="left")
            text = f"{record.record_id}（{record.status.display_name}，{format_money(record.amount)}）"
            ttk.Label(row, text=text, style="Card.TLabel").pack(side="right")

    def _fill_actions(self, detail: RecordDetail) -> None:
        """填充可用操作按钮。

        :param detail: 记录详情。
        """
        for child in self.action_area.winfo_children():
            child.destroy()
        if not detail.available_actions:
            ttk.Label(self.action_area, text="当前状态下没有可执行的操作。",
                      style="CardMuted.TLabel").pack(anchor="w")
            return
        for action in detail.available_actions:
            handler = self._handlers().get(action)
            if handler is None:
                continue
            make_button(self.action_area, action, handler).pack(fill="x", ipady=3, pady=(0, 8))

    def _fill_traces(self, detail: RecordDetail) -> None:
        """填充状态历史时间线。

        :param detail: 记录详情。
        """
        for child in self.trace_area.winfo_children():
            child.destroy()
        if not detail.traces:
            ttk.Label(self.trace_area, text="暂无状态变更记录。", style="CardMuted.TLabel").pack(
                anchor="w"
            )
            return
        for trace in detail.traces:
            row = ttk.Frame(self.trace_area, style="Card.TFrame")
            row.pack(fill="x", pady=(0, 10))
            tk.Label(
                row,
                text="●",
                background=theme.CARD,
                foreground=theme.BRAND,
                font=(theme.FONT, 9),
            ).pack(side="left")
            body = ttk.Frame(row, style="Card.TFrame")
            body.pack(side="left", fill="x", expand=True, padx=(8, 0))
            ttk.Label(body, text=trace.action.display_name, style="Card.TLabel").pack(anchor="w")
            transition = self._transition_text(trace.from_status, trace.to_status)
            ttk.Label(
                body,
                text=f"{trace.actor_name or '系统'} · {trace.occurred_at:%Y-%m-%d %H:%M:%S}"
                f" · {transition}",
                style="CardMuted.TLabel",
            ).pack(anchor="w", pady=(2, 0))
            if trace.reason:
                ttk.Label(body, text=f"原因：{trace.reason}", style="CardWarn.TLabel").pack(
                    anchor="w", pady=(2, 0)
                )

    @staticmethod
    def _transition_text(
        source: Optional[RecordStatus], target: Optional[RecordStatus]
    ) -> str:
        """格式化状态流转说明。

        :param source: 原状态。
        :param target: 新状态。
        :return: 流转说明文字。
        """
        if source is None and target is None:
            return "状态变更"
        source_text = source.display_name if source is not None else "—"
        target_text = target.display_name if target is not None else "—"
        return f"{source_text} → {target_text}"

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    def _handlers(self) -> Dict[str, Callable[[], None]]:
        """返回动作名称与处理函数的对应表。

        :return: 动作映射表。
        """
        return {
            "编辑草稿": self._on_edit,
            "提交审核": self._on_submit,
            "重新提交": self._on_submit,
            "审核通过": self._on_approve,
            "审核驳回": self._on_reject,
            "作废记录": self._on_void,
            "撤回记录": self._on_withdraw,
            "发起冲正": self._on_reverse,
        }

    def _on_edit(self) -> None:
        """进入草稿编辑。"""
        self.app.open_record_form(self.record_id)

    @guard
    def _on_submit(self) -> None:
        """提交审核。"""
        self.context.records.submit(self.user_id, self.ledger_id, self.record_id)
        show_info(self, "记录已提交审核。")
        self.refresh()

    @guard
    def _on_approve(self) -> None:
        """审核通过。"""
        self.context.audits.approve(self.user_id, self.ledger_id, self.record_id)
        show_info(self, "记录已审核通过并计入统计。")
        self.refresh()

    @guard
    def _on_reject(self) -> None:
        """驳回记录，需要填写原因。"""
        reason = ask_reason(self, "驳回记录", "请填写驳回原因：")
        if not reason:
            return
        self.context.audits.reject(self.user_id, self.ledger_id, self.record_id, reason)
        show_info(self, "记录已驳回。")
        self.refresh()

    @guard
    def _on_void(self) -> None:
        """作废记录，需要填写原因。"""
        reason = ask_reason(self, "作废记录", "请填写作废原因：")
        if not reason:
            return
        self.context.audits.void_record(self.user_id, self.ledger_id, self.record_id, reason)
        show_info(self, "记录已作废。")
        self.refresh()

    @guard
    def _on_withdraw(self) -> None:
        """撤回记录。"""
        self.context.records.withdraw(self.user_id, self.ledger_id, self.record_id)
        show_info(self, "记录已撤回为草稿。")
        self.refresh()

    @guard
    def _on_reverse(self) -> None:
        """发起冲正。"""
        reversal = self.context.records.create_reversal(
            self.user_id, self.ledger_id, self.record_id
        )
        show_info(self, f"冲正记录已创建：{reversal.record_id}，请提交审核。")
        self.app.open_record_detail(reversal.record_id)


__all__ = ["RecordDetailPage"]

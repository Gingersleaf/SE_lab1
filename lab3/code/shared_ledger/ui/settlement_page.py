"""结算单详情页面。

展示转账方案、成员应收应付净额、确认进度与历史结算单，并提供确认、
申诉与裁决操作。结算单在生成时已把计算结果与涉及记录存为快照，
页面不会用账本当前数据改写已生成结算单的内容。
"""

# pylint: disable=attribute-defined-outside-init  # tkinter 控件在多层构建方法中创建，属于构造过程的一部分

# pylint: disable=too-many-instance-attributes  # tkinter 页面需要持有多个控件引用
# pylint: disable=too-many-locals  # 结算单字段较多，集中在一个方法里更清晰

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

from ..domain.entities import Settlement
from ..domain.enums import RecordType
from ..service.settlement_service import VERDICT_MAINTAIN, VERDICT_VOID, SettlementDetail
from ..support.state_guard import StateGuard
from .widgets import (
    Card,
    LedgerPage,
    ask_reason,
    format_money,
    format_signed,
    guard,
    make_button,
    make_combo,
    make_entry,
    make_table,
    set_rows,
    show_info,
)

PLAN_COLUMNS = (
    ("seq", "序号", 60, "center"),
    ("from", "转出方", 150, "w"),
    ("to", "转入方", 150, "w"),
    ("amount", "金额", 130, "e"),
    ("state", "状态", 130, "center"),
)

MEMBER_COLUMNS = (
    ("name", "成员", 150, "w"),
    ("role", "角色", 100, "center"),
    ("income", "收入合计", 110, "e"),
    ("expense", "支出合计", 110, "e"),
    ("net", "净额", 120, "e"),
    ("state", "确认状态", 110, "center"),
)

HISTORY_COLUMNS = (
    ("id", "结算单号", 160, "w"),
    ("status", "状态", 100, "center"),
    ("created", "生成时间", 150, "center"),
)

SNAPSHOT_LIMIT = 200


class SettlementPage(LedgerPage):
    """结算单详情页面。"""

    def __init__(self, master: tk.Misc, app: object, **kwargs: object) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, app, **kwargs)
        self.settlement_id = ""
        self.detail: Optional[SettlementDetail] = None
        self.history: List[Settlement] = []
        self.member_roles: Dict[str, str] = {}
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
        """搭建标题与操作按钮。"""
        header = ttk.Frame(self)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.title_label = ttk.Label(header, text="结算单", style="Title.TLabel")
        self.title_label.pack(anchor="w")
        self.subtitle_label = ttk.Label(header, text="", style="Sub.TLabel")
        self.subtitle_label.pack(anchor="w", pady=(6, 0))
        actions = ttk.Frame(header)
        actions.pack(anchor="e", pady=(8, 0))
        self.create_button = make_button(actions, "发起结算", self._on_create, "Primary.TButton")
        self.create_button.pack(side="left")
        self.confirm_button = make_button(actions, "确认本单", self._on_confirm)
        self.confirm_button.pack(side="left", padx=(8, 0))
        self.appeal_button = make_button(actions, "发起申诉", self._on_appeal)
        self.appeal_button.pack(side="left", padx=(8, 0))

    def _build_body(self) -> None:
        """搭建左右两栏内容。"""
        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        right = ttk.Frame(self)
        right.grid(row=1, column=1, sticky="nsew")

        self.plan_card = Card(
            left, "转账方案", "按成员净额拆分为「该收」与「该付」两拨，排序后依次配对"
        )
        self.plan_card.pack(fill="x")
        holder, self.plan_tree = make_table(self.plan_card.body, PLAN_COLUMNS, height=5)
        holder.pack(fill="both", expand=True)
        ttk.Label(
            self.plan_card.body,
            text="本方案仅给出建议转账路线，不接入任何真实支付渠道，成员需自行线下转账。",
            style="CardSub.TLabel",
        ).pack(anchor="w", pady=(8, 0))

        self.member_card = Card(
            left, "成员应收应付净额", "净额与确认状态取自结算单快照"
        )
        self.member_card.pack(fill="both", expand=True, pady=(14, 0))
        holder2, self.member_tree = make_table(self.member_card.body, MEMBER_COLUMNS, height=6)
        holder2.pack(fill="both", expand=True)
        self.member_hint = ttk.Label(self.member_card.body, text="", style="CardSub.TLabel")
        self.member_hint.pack(anchor="w", pady=(8, 0))

        self.history_card = Card(right, "历史结算单")
        self.history_card.pack(fill="x")
        holder3, self.history_tree = make_table(self.history_card.body, HISTORY_COLUMNS, height=5)
        holder3.pack(fill="both", expand=True)
        self.history_tree.bind("<Double-1>", lambda _event: self._on_open_selected())

        self.verdict_card = Card(right, "管理员裁决", "裁决后不再要求成员重新确认")
        self.verdict_card.pack(fill="x", pady=(14, 0))
        self.verdict_area = ttk.Frame(self.verdict_card.body)
        self.verdict_area.pack(fill="x")
        area = self.verdict_area
        self.verdict_combo = make_combo(area, (VERDICT_MAINTAIN, VERDICT_VOID), width=10)
        self.verdict_combo.grid(row=0, column=0, sticky="w")
        self.verdict_reason = make_entry(area, width=34)
        self.verdict_reason.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.verdict_button = make_button(area, "提交裁决", self._on_verdict, "Danger.TButton")
        self.verdict_button.grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Label(area, text="裁决结论", style="CardMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Label(area, text="裁决理由（必填）", style="CardMuted.TLabel").grid(
            row=1, column=1, sticky="w", pady=(4, 0)
        )

        self.snapshot_card = Card(right, "结算快照")
        self.snapshot_card.pack(fill="x", pady=(14, 0))
        self.snapshot_area = ttk.Frame(self.snapshot_card.body)
        self.snapshot_area.pack(fill="x")

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def open_settlement(self, settlement_id: str = "") -> None:
        """打开结算单；未指定时展示最新一张。

        :param settlement_id: 结算单标识。
        """
        if settlement_id:
            self.settlement_id = settlement_id
        self.refresh()

    def refresh(self) -> None:
        """重新读取结算单数据。"""
        self._load_history()
        self._load_roles()
        if not self.settlement_id and self.history:
            self.settlement_id = self.history[0].settlement_id
        if not self.settlement_id:
            self.title_label.configure(text="结算单")
            self.subtitle_label.configure(text="账本内还没有结算单，可由管理员发起结算。")
            set_rows(self.plan_tree, [])
            set_rows(self.member_tree, [])
            return
        self.detail = self.context.settlements.get_settlement(
            self.user_id, self.ledger_id, self.settlement_id
        )
        settlement = self.detail.settlement
        self.title_label.configure(
            text=f"结算单 {settlement.settlement_id} · {settlement.status.display_name}"
        )
        self.subtitle_label.configure(
            text=f"生成于 {settlement.created_at:%Y-%m-%d %H:%M} · "
            f"确认进度 {self.detail.confirmed_count}/{self.detail.total_members}"
        )
        self._fill_plan()
        self._fill_members()
        self._fill_snapshot()
        self._sync_actions(settlement)

    def _load_history(self) -> None:
        """读取历史结算单列表。"""
        self.history = self.context.settlements.list_settlements(self.user_id, self.ledger_id)
        rows = [
            (
                (
                    item.settlement_id,
                    item.status.display_name,
                    item.created_at.strftime("%Y-%m-%d %H:%M"),
                ),
                ("muted",) if item.status.value == "VOIDED" else (),
            )
            for item in self.history
        ]
        set_rows(self.history_tree, rows)

    def _load_roles(self) -> None:
        """读取成员角色，供结算明细展示。"""
        members = self.context.members.list_members(self.user_id, self.ledger_id)
        self.member_roles = {
            item.member.member_id: item.member.role.display_name for item in members
        }

    def _fill_plan(self) -> None:
        """填充转账方案表。"""
        rows = [
            (
                (
                    str(item.seq),
                    item.from_member_name or "—",
                    item.to_member_name or "—",
                    format_money(item.amount),
                    "待线下转账",
                ),
                (),
            )
            for item in self.detail.plan
        ]
        set_rows(self.plan_tree, rows)
        if not rows:
            ttk.Label(
                self.plan_card.body,
                text="本结算单没有需要转账的条目：参与成员的净额同向，无需相互转账。",
                style="CardMuted.TLabel",
            ).pack(anchor="w", pady=(6, 0))

    def _fill_members(self) -> None:
        """填充成员应收应付净额表。"""
        totals = self._snapshot_totals()
        rows = []
        for item in self.detail.members:
            income, expense = totals.get(item.member_id, (None, None))
            state = "已确认" if item.confirmed else "未确认"
            if item.appealed:
                state = "已申诉"
            net_text = format_signed(item.net_amount)
            if item.net_amount > 0:
                net_text = f"应收 {format_money(item.net_amount)}"
            elif item.net_amount < 0:
                net_text = f"应付 {format_money(-item.net_amount)}"
            rows.append(
                (
                    (
                        item.member_name or "—",
                        self.member_roles.get(item.member_id, "—"),
                        format_money(income) if income is not None else "—",
                        format_money(expense) if expense is not None else "—",
                        net_text,
                        state,
                    ),
                    ("income",) if item.net_amount > 0 else (),
                )
            )
        set_rows(self.member_tree, rows)
        self.member_hint.configure(
            text=f"成员净额之和等于账本净额（{format_money(self.detail.ledger_net)}），"
            "与转账方案金额之和一致。"
        )

    def _snapshot_totals(self) -> Dict[str, Tuple[Optional[Decimal], Optional[Decimal]]]:
        """按结算快照还原每位成员的收入与支出合计。

        冲正记录在统计中取相反方向，这里保持同一口径，使收入合计减去
        支出合计等于结算单快照中的净额。

        :return: 成员标识到 ``(收入合计, 支出合计)`` 的映射。
        """
        totals: Dict[str, Tuple[Optional[Decimal], Optional[Decimal]]] = {}
        record_ids = self.detail.settlement.snapshot_record_ids[:SNAPSHOT_LIMIT]
        for record_id in record_ids:
            record_detail = self.context.records.get_detail(
                self.user_id, self.ledger_id, record_id
            )
            record = record_detail.record
            direction = -1 if record.reversal_of_id else 1
            for share in record_detail.shares:
                income, expense = totals.get(share.member_id, (Decimal("0.00"), Decimal("0.00")))
                if record.type is RecordType.INCOME:
                    income = income + share.amount * direction
                else:
                    expense = expense + share.amount * direction
                totals[share.member_id] = (income, expense)
        return totals

    def _fill_snapshot(self) -> None:
        """填充结算快照说明。"""
        for child in self.snapshot_area.winfo_children():
            child.destroy()
        settlement = self.detail.settlement
        rows = (
            ("快照生成时间", settlement.created_at.strftime("%Y-%m-%d %H:%M:%S")),
            ("纳入的已通过记录", f"{len(settlement.snapshot_record_ids)} 条"),
            ("排除的记录", "草稿 / 待审核 / 已驳回 / 已作废"),
            ("裁决结论", settlement.verdict or "—"),
            ("裁决理由", settlement.verdict_reason or "—"),
            ("已作废结算单", "不可恢复"),
        )
        for label, value in rows:
            row = ttk.Frame(self.snapshot_area, style="Card.TFrame")
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, style="CardMuted.TLabel").pack(side="left")
            ttk.Label(row, text=value, style="Card.TLabel").pack(side="right")
        ttk.Label(
            self.snapshot_area,
            text="结算单生成时已把计算结果与涉及记录存为快照，之后账本新增记录不追溯修改本单。",
            style="CardWarn.TLabel",
            wraplength=320,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

    def _sync_actions(self, settlement: Settlement) -> None:
        """按结算单状态显示可用操作。

        :param settlement: 结算单实体。
        """
        actions = StateGuard.available_settlement_actions(settlement.status)
        self.confirm_button.configure(state="normal" if "确认结算单" in actions else "disabled")
        self.appeal_button.configure(state="normal" if "结算申诉" in actions else "disabled")
        verdict_state = "normal" if "结算裁决" in actions else "disabled"
        self.verdict_button.configure(state=verdict_state)

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    @guard
    def _on_create(self) -> None:
        """发起结算。"""
        detail = self.context.settlements.create_settlement(self.user_id, self.ledger_id)
        self.settlement_id = detail.settlement.settlement_id
        show_info(self, f"结算单已生成：{self.settlement_id}")
        self.refresh()

    @guard
    def _on_confirm(self) -> None:
        """确认结算单。"""
        self.context.settlements.confirm(self.user_id, self.ledger_id, self.settlement_id)
        show_info(self, "已确认本结算单。")
        self.refresh()

    @guard
    def _on_appeal(self) -> None:
        """对结算单发起申诉。"""
        reason = ask_reason(self, "结算申诉", "请填写申诉原因：")
        if not reason:
            return
        self.context.settlements.appeal(
            self.user_id, self.ledger_id, self.settlement_id, reason
        )
        show_info(self, "申诉已提交，等待管理员裁决。")
        self.refresh()

    @guard
    def _on_verdict(self) -> None:
        """管理员对争议结算单作出裁决。"""
        reason = self.verdict_reason.get().strip()
        if not reason:
            show_info(self, "请填写裁决理由。")
            return
        self.context.settlements.verdict(
            self.user_id,
            self.ledger_id,
            self.settlement_id,
            self.verdict_combo.get(),
            reason,
        )
        self.verdict_reason.delete(0, "end")
        show_info(self, "裁决已提交。")
        self.refresh()

    def _on_open_selected(self) -> None:
        """打开历史列表中选中的结算单。"""
        selection = self.history_tree.selection()
        if not selection:
            return
        values = self.history_tree.item(selection[0], "values")
        if not values:
            return
        self.settlement_id = str(values[0])
        self.refresh()


__all__ = ["SettlementPage"]

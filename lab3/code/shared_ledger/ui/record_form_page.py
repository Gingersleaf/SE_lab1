"""记一笔（记录录入）页面。

表单字段与实验二 UI 原型「记一笔」一致：收支类型、金额、分类、
记账日期、付款人、备注与分摊成员勾选。金额校验、分摊与状态流转
全部由记录服务负责，页面只做输入提示。
"""

# pylint: disable=attribute-defined-outside-init  # tkinter 控件在多层构建方法中创建，属于构造过程的一部分

# pylint: disable=too-many-instance-attributes  # tkinter 页面需要持有多个控件引用
# pylint: disable=too-many-locals  # 表单字段较多，集中在构建方法里更清晰

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import ttk
from typing import Dict, List, Optional
from uuid import uuid4

from ..domain.entities import Record
from ..domain.enums import RecordType
from ..service.record_service import RecordDraftInput
from .widgets import (
    Card,
    LedgerPage,
    format_amount,
    guard,
    make_button,
    make_combo,
    make_entry,
    parse_amount,
    show_info,
)

MAX_DECIMAL_PLACES = 2


class RecordFormPage(LedgerPage):
    """记录录入与草稿编辑页面。"""

    def __init__(self, master: tk.Misc, app: object, **kwargs: object) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, app, **kwargs)
        self.editing_id = ""
        self.editing_version: Optional[int] = None
        self.category_ids: Dict[str, str] = {}
        self.payer_ids: Dict[str, str] = {}
        self.participants: Dict[str, tk.BooleanVar] = {}
        self.readonly_notes: Dict[str, str] = {}
        self._build()

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def _build(self) -> None:
        """搭建表单结构。"""
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self._build_form()

    def _build_header(self) -> None:
        """搭建标题与说明。"""
        header = ttk.Frame(self)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.title_label = ttk.Label(header, text="记一笔", style="Title.TLabel")
        self.title_label.pack(anchor="w")
        ttk.Label(
            header,
            text="草稿可反复编辑；提交后进入待审核，管理员审核通过才计入统计。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(6, 0))

    def _build_form(self) -> None:
        """搭建左右两栏内容。"""
        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        right = ttk.Frame(self)
        right.grid(row=1, column=1, sticky="nsew")
        self._build_basic_card(left)
        self._build_share_card(left)
        self._build_action_card(right)

    def _build_basic_card(self, parent: tk.Misc) -> None:
        """搭建基本信息表单。"""
        card = Card(parent, "记录内容", "金额最多保留两位小数，月份按记账日期归属统计")
        card.pack(fill="x")
        area = ttk.Frame(card.body)
        area.pack(fill="x")

        self.type_var = tk.StringVar(value="支出")
        type_row = ttk.Frame(area, style="Card.TFrame")
        type_row.grid(row=0, column=0, sticky="w")
        ttk.Label(type_row, text="收支类型", style="Card.TLabel").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            type_row, text="支出", value="支出", variable=self.type_var,
            style="Card.TRadiobutton"
        ).pack(side="left")
        ttk.Radiobutton(
            type_row, text="收入", value="收入", variable=self.type_var,
            style="Card.TRadiobutton"
        ).pack(side="left", padx=(12, 0))

        self.amount_entry = make_entry(area, width=18)
        self.amount_entry.grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.amount_entry.bind("<KeyRelease>", lambda _event: self._update_hints())
        self.amount_hint = ttk.Label(area, text="", style="CardSub.TLabel")
        self.amount_hint.grid(row=2, column=0, sticky="w")

        self.category_combo = make_combo(area, ("",), width=14)
        self.category_combo.grid(row=1, column=1, sticky="w", padx=(16, 0), pady=(12, 0))
        ttk.Label(area, text="分类", style="Card.TLabel").grid(
            row=0, column=1, sticky="w", padx=(16, 0)
        )

        self.date_entry = make_entry(area, width=14, text=date.today().isoformat())
        self.date_entry.grid(row=1, column=2, sticky="w", padx=(16, 0), pady=(12, 0))
        ttk.Label(area, text="记账日期", style="Card.TLabel").grid(
            row=0, column=2, sticky="w", padx=(16, 0)
        )

        self.payer_combo = make_combo(area, ("",), width=14)
        self.payer_combo.grid(row=1, column=3, sticky="w", padx=(16, 0), pady=(12, 0))
        ttk.Label(area, text="付款人", style="Card.TLabel").grid(
            row=0, column=3, sticky="w", padx=(16, 0)
        )

        self.note_entry = make_entry(area, width=46)
        self.note_entry.grid(row=3, column=0, columnspan=4, sticky="w", pady=(14, 0))
        ttk.Label(area, text="备注", style="Card.TLabel").grid(
            row=4, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Label(
            area,
            text="本版本仅支持文字、金额、分类与时间，不支持图片凭证。",
            style="CardSub.TLabel",
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(2, 0))

    def _build_share_card(self, parent: tk.Misc) -> None:
        """搭建分摊成员勾选区。"""
        card = Card(parent, "分摊成员", "按参与成员均摊；余数分配给加入账本最早的参与者")
        card.pack(fill="both", expand=True, pady=(14, 0))
        self.share_area = ttk.Frame(card.body)
        self.share_area.pack(fill="both", expand=True)
        self.share_hint = ttk.Label(card.body, text="", style="CardSub.TLabel")
        self.share_hint.pack(anchor="w", pady=(8, 0))

    def _build_action_card(self, parent: tk.Misc) -> None:
        """搭建保存与提交操作区。"""
        card = Card(parent, "保存与提交")
        card.pack(fill="x")
        area = ttk.Frame(card.body)
        area.pack(fill="x")
        self.submit_button = make_button(area, "提交审核", self._on_submit, "Primary.TButton")
        self.submit_button.pack(fill="x", ipady=3)
        self.save_button = make_button(area, "保存草稿", self._on_save)
        self.save_button.pack(fill="x", ipady=3, pady=(10, 0))
        make_button(area, "取消", self._on_cancel).pack(fill="x", ipady=3, pady=(10, 0))

        rules = Card(parent, "填写规则")
        rules.pack(fill="x", pady=(14, 0))
        for label, value in (
            ("金额取值", "必须大于 0"),
            ("金额精度", "最多两位小数"),
            ("单笔上限", "¥ 500,000.00（提交时校验）"),
            ("分摊人数", "至少 1 人"),
            ("付款人", "恰好 1 人，且不能是只读成员"),
            ("分摊合计", "必须等于记录金额（保存时由系统校验）"),
        ):
            row = ttk.Frame(rules.body, style="Card.TFrame")
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, style="CardMuted.TLabel").pack(side="left")
            ttk.Label(row, text=value, style="Card.TLabel").pack(side="right")

    # ------------------------------------------------------------------
    # 打开与填充
    # ------------------------------------------------------------------
    def open_form(self, record_id: str = "") -> None:
        """打开表单；传入记录标识时进入编辑模式。

        :param record_id: 待编辑的记录标识，空字符串表示新建。
        """
        self.editing_id = record_id
        self.editing_version = None
        self._reload_options()
        self._reset_inputs()
        if record_id:
            self._load_record(record_id)
        self._update_hints()
        self.title_label.configure(text="编辑记录" if record_id else "记一笔")

    def _reset_inputs(self) -> None:
        """清空输入控件。"""
        self.type_var.set("支出")
        self.amount_entry.delete(0, "end")
        self.note_entry.delete(0, "end")
        self.date_entry.delete(0, "end")
        self.date_entry.insert(0, date.today().isoformat())
        for variable in self.participants.values():
            variable.set(False)

    def _reload_options(self) -> None:
        """刷新分类、付款人与分摊成员的可选项。"""
        categories = [
            item
            for item in self.context.categories.list_categories(self.user_id, self.ledger_id)
            if item.status.value == "ENABLED"
        ]
        self.category_ids = {item.name: item.category_id for item in categories}
        self.category_combo["values"] = tuple(self.category_ids)
        if self.category_ids:
            self.category_combo.current(0)

        members = self.context.members.list_members(self.user_id, self.ledger_id)
        active = [item.member for item in members if item.member.is_active]
        writable = [item for item in active if item.role.can_write_record]
        self.payer_ids = {item.display_name: item.member_id for item in writable}
        self.payer_combo["values"] = tuple(self.payer_ids)
        if self.payer_ids:
            self.payer_combo.current(0)

        for child in self.share_area.winfo_children():
            child.destroy()
        self.participants = {}
        self.readonly_notes = {}
        for member in active:
            self._add_participant_row(member)

    def _add_participant_row(self, member: object) -> None:
        """添加一行分摊成员勾选项。

        :param member: 成员实体。
        """
        row = ttk.Frame(self.share_area, style="Card.TFrame")
        row.pack(fill="x", pady=3)
        variable = tk.BooleanVar(value=False)
        self.participants[member.member_id] = variable
        allowed = member.role.can_write_record
        if allowed:
            ttk.Checkbutton(row, text="参与分摊", variable=variable).pack(side="left")
        else:
            ttk.Label(row, text="不可选", style="CardMuted.TLabel").pack(side="left")
            self.readonly_notes[member.member_id] = "只读成员不可参与分摊"
        ttk.Label(row, text=member.display_name, style="Card.TLabel").pack(
            side="left", padx=(10, 0)
        )
        ttk.Label(
            row,
            text=member.joined_at.strftime("%Y-%m-%d"),
            style="CardMuted.TLabel",
        ).pack(side="left", padx=(12, 0))
        reason = self.readonly_notes.get(member.member_id, "")
        ttk.Label(row, text=reason, style="CardMuted.TLabel").pack(side="left", padx=(12, 0))

    def _load_record(self, record_id: str) -> None:
        """把已有记录填入表单。

        :param record_id: 记录标识。
        """
        detail = self.context.records.get_detail(self.user_id, self.ledger_id, record_id)
        record = detail.record
        self.editing_version = record.version
        self.type_var.set(record.type.display_name)
        self.amount_entry.insert(0, format_amount(record.amount))
        self.note_entry.insert(0, record.note)
        self.date_entry.delete(0, "end")
        self.date_entry.insert(0, record.record_date.isoformat())
        self._select_by_name(self.category_combo, record.category_name)
        self._select_by_name(self.payer_combo, record.payer_name)
        selected = {share.member_id for share in detail.shares}
        for member_id, variable in self.participants.items():
            variable.set(member_id in selected)

    @staticmethod
    def _select_by_name(combo: ttk.Combobox, name: str) -> None:
        """在下拉框中选中指定名称。

        :param combo: 下拉框控件。
        :param name: 选项名称。
        """
        values = list(combo["values"])
        if name in values:
            combo.set(name)

    # ------------------------------------------------------------------
    # 校验与保存
    # ------------------------------------------------------------------
    def _update_hints(self) -> None:
        """刷新输入提示。"""
        amount = self._parsed_amount()
        if amount is None:
            self.amount_hint.configure(text="", style="CardSub.TLabel")
        elif amount <= 0:
            self.amount_hint.configure(text="金额必须大于零。", style="CardError.TLabel")
        elif -amount.as_tuple().exponent > MAX_DECIMAL_PLACES:
            self.amount_hint.configure(text="金额最多保留两位小数。", style="CardError.TLabel")
        else:
            self.amount_hint.configure(text="金额格式正确。", style="CardOk.TLabel")

        count = len(self._selected_participants())
        if count == 0:
            self.share_hint.configure(text="尚未选择分摊成员，至少需要 1 人。", style="CardError.TLabel")
        else:
            self.share_hint.configure(
                text=f"已选 {count} 人参与分摊，保存时由系统自动均摊并校验分摊合计。",
                style="CardSub.TLabel",
            )

    def _parsed_amount(self) -> Optional[Decimal]:
        """返回输入框中的金额。

        :return: 金额；输入非法时返回 ``None``。
        """
        return parse_amount(self.amount_entry.get())

    def _selected_participants(self) -> List[str]:
        """返回勾选参与分摊的成员标识。"""
        return [
            member_id
            for member_id, variable in self.participants.items()
            if variable.get() and member_id not in self.readonly_notes
        ]

    def _build_payload(self) -> Optional[RecordDraftInput]:
        """把表单内容组装成记录输入对象。

        :return: 输入对象；校验不通过时返回 ``None``。
        """
        amount = self._parsed_amount()
        if amount is None or amount <= 0:
            show_info(self, "请填写正确的金额。")
            return None
        category_id = self.category_ids.get(self.category_combo.get(), "")
        if not category_id:
            show_info(self, "请选择分类。")
            return None
        payer_id = self.payer_ids.get(self.payer_combo.get(), "")
        if not payer_id:
            show_info(self, "请选择付款人。")
            return None
        participants = self._selected_participants()
        if not participants:
            show_info(self, "至少选择一位成员参与分摊。")
            return None
        moment = self.date_entry.get().strip()
        try:
            record_date = date.fromisoformat(moment)
        except ValueError:
            show_info(self, "记账日期格式应为 YYYY-MM-DD。")
            return None
        return RecordDraftInput(
            record_type=RecordType.INCOME if self.type_var.get() == "收入" else RecordType.EXPENSE,
            amount=amount,
            category_id=category_id,
            record_date=record_date,
            note=self.note_entry.get().strip(),
            payer_member_id=payer_id,
            participant_member_ids=participants,
        )

    @guard
    def _on_save(self) -> None:
        """保存为草稿。"""
        record = self._store_draft()
        if record is None:
            return
        show_info(self, f"草稿已保存：{record.record_id}")
        self.app.open_record_detail(record.record_id)

    @guard
    def _on_submit(self) -> None:
        """保存并提交审核。"""
        record = self._store_draft()
        if record is None:
            return
        self.context.records.submit(self.user_id, self.ledger_id, record.record_id)
        show_info(self, f"已提交审核：{record.record_id}")
        self.app.open_record_detail(record.record_id)

    def _store_draft(self) -> Optional[Record]:
        """保存草稿，已存在则更新。

        :return: 保存后的记录实体；校验不通过时返回 ``None``。
        """
        payload = self._build_payload()
        if payload is None:
            return None
        if self.editing_id:
            record = self.context.records.update_draft(
                self.user_id,
                self.ledger_id,
                self.editing_id,
                payload,
                expected_version=self.editing_version,
            )
        else:
            record = self.context.records.create_draft(
                self.user_id,
                self.ledger_id,
                payload,
                request_id=f"UI-{uuid4().hex[:16]}",
            )
        self.editing_id = record.record_id
        self.editing_version = record.version
        return record

    def _on_cancel(self) -> None:
        """放弃当前输入，返回记录列表。"""
        self.app.show_page("records")

    def refresh(self) -> None:
        """刷新页面时重新加载可选项。"""
        self._reload_options()


__all__ = ["RecordFormPage"]

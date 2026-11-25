"""成员管理页面。

包含成员列表、邀请链接生成与邀请列表，以及三类角色的权限对照表。
角色调整、移除成员与恢复结算资格都由账本成员服务执行，页面只负责
收集输入并展示结果。
"""

# pylint: disable=attribute-defined-outside-init  # tkinter 控件在多层构建方法中创建，属于构造过程的一部分

# pylint: disable=too-many-instance-attributes  # tkinter 页面需要持有多个控件引用
# pylint: disable=too-many-locals  # 成员表列较多，集中在一个方法里更清晰

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Tuple

from ..domain.entities import Invitation, LedgerMember
from ..domain.enums import Role
from ..domain.errors import LedgerError
from ..service.ledger_member_service import MemberSummary
from .widgets import (
    Card,
    LedgerPage,
    bind_row_menu,
    format_signed,
    guard,
    make_button,
    make_combo,
    make_entry,
    make_table,
    set_rows,
    show_info,
)

MEMBER_COLUMNS = (
    ("name", "成员", 120, "w"),
    ("account", "账号", 100, "w"),
    ("role", "角色", 90, "center"),
    ("joined", "加入时间", 100, "center"),
    ("settle", "结算资格", 90, "center"),
    ("records", "录入记录", 80, "e"),
    ("net", "净额", 110, "e"),
    ("action", "操作", 170, "w"),
)

INVITE_COLUMNS = (
    ("role", "邀请角色", 100, "center"),
    ("status", "状态", 90, "center"),
    ("expires", "有效期至", 130, "center"),
    ("used", "使用次数", 90, "center"),
    ("created", "创建时间", 130, "center"),
    ("action", "操作", 80, "center"),
)

ROLE_ROWS: Tuple[Tuple[str, str], ...] = (
    ("录入 / 编辑草稿", "write"),
    ("提交 / 撤回记录", "write"),
    ("审核通过 / 驳回 / 作废", "audit"),
    ("发起冲正", "write"),
    ("查看统计与记录", "read"),
    ("发起结算", "admin"),
    ("确认 / 申诉结算单", "settle"),
    ("查询操作日志", "log"),
    ("邀请 / 移除成员、调整角色", "admin"),
)


class MemberPage(LedgerPage):
    """成员管理页面。"""

    def __init__(self, master: tk.Misc, app: object, **kwargs: object) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, app, **kwargs)
        self.summaries: List[MemberSummary] = []
        self.invitations: List[Invitation] = []
        self._build()

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def _build(self) -> None:
        """搭建页面结构。"""
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="成员管理", style="Title.TLabel").pack(anchor="w")
        self.subtitle = ttk.Label(header, text="", style="Sub.TLabel")
        self.subtitle.pack(anchor="w", pady=(6, 0))

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        self.member_card = Card(body, "成员列表", "管理员角色不可转让，管理员不能被移除")
        self.member_card.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        holder, self.member_tree = make_table(self.member_card.body, MEMBER_COLUMNS, height=6)
        holder.pack(fill="both", expand=True)
        bind_row_menu(self.member_tree, "action", self._member_actions)
        self._build_role_card(body)

        bottom = ttk.Frame(self)
        bottom.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=1)
        self._build_invite_card(bottom)
    def _build_invite_card(self, parent: tk.Misc) -> None:
        """搭建邀请链接卡片。

        :param parent: 父容器。
        """
        card = Card(parent, "生成邀请链接", "仅管理员可邀请，被邀请人打开链接后自动获得指定角色")
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        area = ttk.Frame(card.body)
        area.pack(fill="x")
        self.invite_role = make_combo(area, ("记账成员", "只读成员"), width=12)
        self.invite_role.current(0)
        self.invite_role.grid(row=0, column=0, sticky="w")
        self.invite_days = make_combo(area, ("1", "7", "30"), width=6)
        self.invite_days.current(1)
        self.invite_days.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.invite_uses = make_combo(area, ("1", "5", "10"), width=6)
        self.invite_uses.current(0)
        self.invite_uses.grid(row=0, column=2, sticky="w", padx=(12, 0))
        make_button(area, "生成邀请链接", self._on_create_invite, "Primary.TButton").grid(
            row=0, column=3, sticky="w", padx=(12, 0)
        )
        for index, text in enumerate(("邀请后角色", "有效期（天）", "可使用次数", "")):
            ttk.Label(area, text=text, style="CardMuted.TLabel").grid(
                row=1, column=index, sticky="w", pady=(4, 0)
            )

        self.link_entry = make_entry(card.body, width=52, text="尚未生成邀请链接")
        self.link_entry.configure(state="readonly")
        self.link_entry.pack(fill="x", pady=(12, 0))
        link_buttons = ttk.Frame(card.body, style="Card.TFrame")
        link_buttons.pack(fill="x")
        make_button(link_buttons, "复制链接", self._on_copy_link, "Small.TButton").pack(side="left")
        make_button(link_buttons, "撤销当前链接", self._on_revoke_current, "Small.TButton").pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            card.body,
            text="邀请链接的有效期与可使用次数可配置；链接过期、被撤销或次数用尽时会给出明确提示。",
            style="CardSub.TLabel",
        ).pack(anchor="w", pady=(10, 0))

        self.invite_card = Card(parent, "邀请列表")
        self.invite_card.grid(row=0, column=1, sticky="nsew")
        holder, self.invite_tree = make_table(self.invite_card.body, INVITE_COLUMNS, height=4)
        holder.pack(fill="both", expand=True)
        bind_row_menu(self.invite_tree, "action", self._invite_actions)

    def _build_role_card(self, parent: tk.Misc) -> None:
        """搭建角色权限对照卡片。

        :param parent: 父容器。
        """
        card = Card(parent, "角色权限对照", "三类角色的操作边界")
        card.grid(row=0, column=1, sticky="nsew")
        columns = (
            ("action", "操作", 220, "w"),
            ("admin", "管理员", 90, "center"),
            ("writer", "记账成员", 90, "center"),
            ("reader", "只读成员", 90, "center"),
        )
        holder, self.role_tree = make_table(card.body, columns, height=6)
        holder.pack(fill="both", expand=True)
        ttk.Label(
            card.body,
            text="越权操作一律被拒绝并写入操作日志，拦截不静默丢弃。",
            style="CardSub.TLabel",
        ).pack(anchor="w", pady=(8, 0))

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """重新读取成员与邀请数据。"""
        self.summaries = self.context.members.list_members(self.user_id, self.ledger_id)
        self.subtitle.configure(
            text=f"当前 {len(self.summaries)} 位成员（含已退出），上限 50 位"
        )
        set_rows(self.member_tree, [self._member_row(item) for item in self.summaries])
        self._refresh_invitations()
        self._fill_role_table()

    def _member_row(self, summary: MemberSummary) -> tuple:
        """把成员汇总转换成表格行。

        :param summary: 成员汇总。
        :return: ``(各列取值, 行标签)``。
        """
        member = summary.member
        settle = "参与结算" if member.settlement_eligible else "不参与结算"
        values = (
            member.display_name + ("（我）" if member.user_id == self.user_id else ""),
            member.account_name or "—",
            member.role.display_name,
            member.joined_at.strftime("%Y-%m-%d"),
            settle,
            str(summary.record_count),
            format_signed(summary.net_amount),
            self._action_text(member),
        )
        tags = ("muted",) if not member.is_active else ()
        return values, tags

    @staticmethod
    def _action_text(member: LedgerMember) -> str:
        """返回成员行上的操作提示文字。

        :param member: 成员实体。
        :return: 操作提示文字。
        """
        if member.role is Role.ADMIN:
            return "管理员不可移除"
        actions = []
        if not member.settlement_eligible and member.role is not Role.READER:
            actions.append("恢复结算资格")
        else:
            actions.append("调整角色")
        if member.is_active:
            actions.append("移出账本")
        return " · ".join(actions)

    def _member_actions(self, row: str) -> List[Tuple[str, Callable[[], None]]]:
        """返回某一行成员可执行的操作。

        :param row: 表格行标识。
        :return: ``(菜单文字, 回调)`` 列表。
        """
        summary = self._summary_for(row)
        if summary is None:
            return []
        member = summary.member
        if member.role is Role.ADMIN:
            return []
        actions: List[Tuple[str, Callable[[], None]]] = []
        if member.role is Role.WRITER:
            actions.append(("调整为只读成员", lambda: self._change_role(member, Role.READER)))
        else:
            actions.append(("调整为记账成员", lambda: self._change_role(member, Role.WRITER)))
        if member.settlement_eligible:
            actions.append(("移出账本", lambda: self._remove_member(member)))
        elif member.role is not Role.READER:
            actions.append(("恢复结算资格", lambda: self._restore(member)))
        return actions

    def _summary_for(self, row: str) -> object:
        """按表格行标识找到对应的成员汇总。

        :param row: 表格行标识。
        :return: 成员汇总；找不到时返回 ``None``。
        """
        values = self.member_tree.item(row, "values")
        if not values:
            return None
        name = str(values[0]).replace("（我）", "")
        for item in self.summaries:
            if item.member.display_name == name:
                return item
        return None

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    @guard
    def _change_role(self, member: LedgerMember, role: Role) -> None:
        """调整成员角色。

        :param member: 成员实体。
        :param role: 目标角色。
        """
        self.context.members.change_role(
            self.user_id, self.ledger_id, member.user_id, role
        )
        show_info(self, f"{member.display_name} 的角色已调整为{role.display_name}。")
        self.refresh()

    @guard
    def _remove_member(self, member: LedgerMember) -> None:
        """把成员移出账本。

        :param member: 成员实体。
        """
        self.context.members.remove_member(self.user_id, self.ledger_id, member.user_id)
        show_info(self, f"{member.display_name} 已被移出账本，历史记录保留。")
        self.refresh()

    @guard
    def _restore(self, member: LedgerMember) -> None:
        """恢复成员的结算资格。

        :param member: 成员实体。
        """
        self.context.members.restore_settlement_eligibility(
            self.user_id, self.ledger_id, member.user_id
        )
        show_info(self, f"{member.display_name} 的结算资格已恢复。")
        self.refresh()

    @guard
    def _on_create_invite(self) -> None:
        """生成邀请链接。"""
        role = Role.READER if self.invite_role.get() == "只读成员" else Role.WRITER
        invitation = self.context.invitations.create_invitation(
            self.user_id,
            self.ledger_id,
            role,
            valid_days=int(self.invite_days.get()),
            max_uses=int(self.invite_uses.get()),
        )
        self.link_entry.configure(state="normal")
        self.link_entry.delete(0, "end")
        self.link_entry.insert(0, f"https://ledger.example.com/invite/{invitation.token}")
        self.link_entry.configure(state="readonly")
        show_info(self, "邀请链接已生成。")
        self.refresh()

    def _on_copy_link(self) -> None:
        """把邀请链接复制到剪贴板。"""
        self.clipboard_clear()
        self.clipboard_append(self.link_entry.get())
        show_info(self, "邀请链接已复制到剪贴板。")

    @guard
    def _on_revoke_current(self) -> None:
        """撤销最近生成的邀请链接。"""
        if not self.invitations:
            show_info(self, "当前没有可撤销的邀请链接。")
            return
        self.context.invitations.revoke_invitation(
            self.user_id, self.ledger_id, self.invitations[-1].invitation_id
        )
        show_info(self, "邀请链接已撤销。")
        self.refresh()

    def _refresh_invitations(self) -> None:
        """刷新邀请列表。"""
        try:
            self.invitations = self.context.invitations.list_invitations(
                self.user_id, self.ledger_id
            )
        except LedgerError:
            self.invitations = []
        rows = []
        for item in self.invitations:
            action = "撤销" if item.status.value == "ISSUED" else "—"
            rows.append(
                (
                    (
                        item.invite_role.display_name,
                        item.status.display_name,
                        item.expires_at.strftime("%Y-%m-%d %H:%M"),
                        f"{item.used_count} / {item.max_uses}",
                        item.created_at.strftime("%Y-%m-%d %H:%M"),
                        action,
                    ),
                    ("muted",) if item.status.value != "ISSUED" else (),
                )
            )
        set_rows(self.invite_tree, rows)

    def _invite_actions(self, row: str) -> List[Tuple[str, Callable[[], None]]]:
        """返回某一行邀请可执行的操作。

        :param row: 表格行标识。
        :return: ``(菜单文字, 回调)`` 列表。
        """
        values = self.invite_tree.item(row, "values")
        if not values or values[5] != "撤销":
            return []
        target = self.invitations[self.invite_tree.index(row)]
        return [("撤销链接", lambda: self._revoke(target))]

    @guard
    def _revoke(self, invitation: Invitation) -> None:
        """撤销一条邀请。

        :param invitation: 邀请实体。
        """
        self.context.invitations.revoke_invitation(
            self.user_id, self.ledger_id, invitation.invitation_id
        )
        show_info(self, "邀请链接已撤销。")
        self.refresh()

    def _fill_role_table(self) -> None:
        """填充角色权限对照表。"""
        rows = []
        for label, key in ROLE_ROWS:
            values = (
                label,
                self._capability(Role.ADMIN, key),
                self._capability(Role.WRITER, key),
                self._capability(Role.READER, key),
            )
            rows.append((values, ()))
        set_rows(self.role_tree, rows)

    @staticmethod
    def _capability(role: Role, key: str) -> str:
        """返回某角色在指定操作上的能力描述。

        :param role: 角色。
        :param key: 能力键。
        :return: 能力描述。
        """
        if key == "log":
            if role.can_manage_member:
                return "全账本"
            if role.can_write_record:
                return "仅与自己相关"
            return "待确认"
        flags = {
            "read": True,
            "write": role.can_write_record,
            "audit": role.can_audit_record,
            "admin": role.can_manage_member,
            "settle": role is not Role.READER,
        }
        if key in flags:
            return "✓" if flags[key] else "—"
        return "—"


__all__ = ["MemberPage"]

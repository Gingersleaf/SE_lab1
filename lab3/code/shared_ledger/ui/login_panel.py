"""登录界面。

左侧是系统简介与核心特性说明，右侧是账号口令登录表单。
登录成功后由主窗口接管，进入账本主界面。
"""

# pylint: disable=attribute-defined-outside-init  # tkinter 控件在多层构建方法中创建，属于构造过程的一部分

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Tuple

from ..app import ApplicationContext
from ..domain.entities import User
from ..domain.errors import LedgerError
from . import theme

FEATURES: Tuple[Tuple[str, str], ...] = (
    ("1", "一次消费只记一笔，按参与成员自动均摊，余数归入账最早者"),
    ("2", "草稿 → 提交 → 审核 → 计入统计，状态流转全程受控"),
    ("3", "金额记错走冲正更正，净额自动相抵，不直接改账"),
    ("4", "结算给出转账方案，成员线下转账，账本内容生成即冻结"),
)

GRADIENT_STOPS = ("#1d3f8f", "#2f6fed", "#7f56d9")


def _mix(color1: str, color2: str, ratio: float) -> str:
    """在两种颜色之间线性插值。

    :param color1: 起始颜色。
    :param color2: 结束颜色。
    :param ratio: 插值比例，取值 0 到 1。
    :return: 十六进制颜色串。
    """
    first = [int(color1[index : index + 2], 16) for index in (1, 3, 5)]
    second = [int(color2[index : index + 2], 16) for index in (1, 3, 5)]
    mixed = [
        round(first[pos] + (second[pos] - first[pos]) * ratio) for pos in range(3)
    ]
    return "#" + "".join(f"{value:02x}" for value in mixed)


def _gradient_color(ratio: float) -> str:
    """按位置计算渐变颜色。

    :param ratio: 位置比例，取值 0 到 1。
    :return: 十六进制颜色串。
    """
    segments = len(GRADIENT_STOPS) - 1
    scaled = min(max(ratio, 0.0), 1.0) * segments
    index = min(int(scaled), segments - 1)
    return _mix(GRADIENT_STOPS[index], GRADIENT_STOPS[index + 1], scaled - index)


class LoginPanel(tk.Frame):
    """登录面板。"""

    def __init__(
        self,
        master: tk.Misc,
        context: ApplicationContext,
        on_success: Callable[[User], None],
        **kwargs: Any,
    ) -> None:
        """初始化登录面板。

        :param master: 父容器。
        :param context: 应用上下文，用于调用账号服务。
        :param on_success: 登录成功后的回调，参数为登录用户。
        :param kwargs: 透传给 ``tk.Frame`` 的参数。
        """
        super().__init__(master, background=theme.APP_BG, **kwargs)
        self.context = context
        self.on_success = on_success
        self.account_var = tk.StringVar(value="zhoucy")
        self.password_var = tk.StringVar(value="123456")
        self.hint_var = tk.StringVar(value="")
        self._build()

    def _build(self) -> None:
        """搭建左右两栏布局。"""
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self._build_brand()
        self._build_form()

    def _build_brand(self) -> None:
        """搭建左侧品牌与特性说明。"""
        holder = tk.Frame(self, background=theme.BRAND_DARK)
        holder.grid(row=0, column=0, sticky="nsew")
        strip = tk.Canvas(holder, width=22, highlightthickness=0, borderwidth=0)
        strip.pack(side="left", fill="y")
        strip.bind(
            "<Configure>", lambda event: self._draw_gradient(strip, event.height, horizontal=True)
        )
        content = tk.Frame(holder, background=theme.BRAND_DARK)
        content.pack(side="left", fill="both", expand=True, padx=44)

        logo = tk.Label(
            content,
            text="账",
            font=(theme.FONT, 18, "bold"),
            background="#3b5fbf",
            foreground=theme.WHITE,
            width=3,
        )
        logo.pack(anchor="w", pady=(56, 0))
        tk.Label(
            content,
            text="多人共享记账系统",
            font=(theme.FONT, 16, "bold"),
            background=theme.BRAND_DARK,
            foreground=theme.WHITE,
        ).pack(anchor="w", pady=(12, 0))
        tk.Label(
            content,
            text="Shared Ledger System",
            font=(theme.FONT, 9),
            background=theme.BRAND_DARK,
            foreground="#cfd9f0",
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            content,
            text="一群人，共用一本账",
            font=(theme.FONT, 26, "bold"),
            background=theme.BRAND_DARK,
            foreground=theme.WHITE,
        ).pack(anchor="w", pady=(64, 0))
        tk.Label(
            content,
            text="合租室友、社团与家庭共同消费时，一笔开销只被记录一次。"
            "审核机制保证进入统计的记录都经过确认，关键操作全程可追溯。",
            font=(theme.FONT, 11),
            background=theme.BRAND_DARK,
            foreground="#e6ecfb",
            justify="left",
            wraplength=460,
        ).pack(anchor="w", pady=(16, 0))

        for number, text in FEATURES:
            row = tk.Frame(content, background=theme.BRAND_DARK)
            row.pack(anchor="w", pady=(14, 0))
            tk.Label(
                row,
                text=number,
                font=(theme.FONT, 9, "bold"),
                background="#3b5fbf",
                foreground=theme.WHITE,
                width=2,
            ).pack(side="left", padx=(0, 10))
            tk.Label(
                row,
                text=text,
                font=(theme.FONT, 10),
                background=theme.BRAND_DARK,
                foreground="#e6ecfb",
            ).pack(side="left")

    @staticmethod
    def _draw_gradient(
        canvas: tk.Canvas, length: int, horizontal: bool = False
    ) -> None:
        """在画布上绘制渐变色带。

        :param canvas: 画布控件。
        :param length: 绘制方向上的长度。
        :param horizontal: 是否沿水平方向绘制。
        """
        canvas.delete("gradient")
        bands = 60
        for index in range(bands):
            ratio = index / (bands - 1)
            if horizontal:
                top = length * index / bands
                bottom = length * (index + 1) / bands + 1
                canvas.create_rectangle(
                    0, top, canvas.winfo_width(), bottom,
                    fill=_gradient_color(ratio), outline=""
                )
            else:
                left = length * index / bands
                right = length * (index + 1) / bands + 1
                canvas.create_rectangle(
                    left, 0, right, canvas.winfo_height(),
                    fill=_gradient_color(ratio), outline=""
                )

    def _build_form(self) -> None:
        """搭建右侧登录表单。"""
        holder = tk.Frame(self, background=theme.CARD)
        holder.grid(row=0, column=1, sticky="nsew")
        form = tk.Frame(holder, background=theme.CARD)
        form.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.72)

        tk.Label(
            form,
            text="欢迎回来",
            font=(theme.FONT, 20, "bold"),
            background=theme.CARD,
            foreground=theme.INK,
        ).pack(anchor="w")
        tk.Label(
            form,
            text="登录后可进入你的账本",
            font=(theme.FONT, 10),
            background=theme.CARD,
            foreground=theme.MUTED,
        ).pack(anchor="w", pady=(6, 22))

        tk.Label(
            form, text="账号", font=(theme.FONT, 10), background=theme.CARD, foreground=theme.INK2
        ).pack(anchor="w")
        account_entry = ttk.Entry(form, textvariable=self.account_var, width=32)
        account_entry.pack(fill="x", pady=(6, 16))

        tk.Label(
            form,
            text="口令",
            font=(theme.FONT, 10),
            background=theme.CARD,
            foreground=theme.INK2,
        ).pack(anchor="w")
        password_entry = ttk.Entry(form, textvariable=self.password_var, width=32, show="*")
        password_entry.pack(fill="x", pady=(6, 18))

        ttk.Button(
            form, text="登 录", style="Primary.TButton", command=self._do_login
        ).pack(fill="x", ipady=4)
        self.hint_label = tk.Label(
            form,
            textvariable=self.hint_var,
            font=(theme.FONT, 9),
            background=theme.CARD,
            foreground=theme.RED,
            wraplength=300,
            justify="left",
        )
        self.hint_label.pack(anchor="w", pady=(10, 0))

        note = tk.Frame(form, background=theme.INDIGO_BG)
        note.pack(fill="x", pady=(26, 0))
        tk.Label(
            note,
            text="通过管理员发出的邀请链接进入的成员，登录后自动加入对应账本"
            "并获得指定角色，无需管理员二次审批。",
            font=(theme.FONT, 9),
            background=theme.INDIGO_BG,
            foreground=theme.INDIGO,
            justify="left",
            wraplength=320,
        ).pack(anchor="w", padx=12, pady=12)

        tk.Label(
            form,
            text="演示账号：zhoucy（管理员） / jiangzc（记账成员） / chenmo（只读成员），"
            "口令均为 123456",
            font=(theme.FONT, 8),
            background=theme.CARD,
            foreground=theme.FAINT,
            wraplength=320,
            justify="left",
        ).pack(anchor="w", pady=(18, 0))

        password_entry.bind("<Return>", lambda _event: self._do_login())

    def _do_login(self) -> None:
        """校验账号口令并登录。"""
        account = self.account_var.get().strip()
        password = self.password_var.get()
        if not account or not password:
            self.hint_var.set("请填写账号与口令。")
            return
        try:
            user = self.context.auth.login(account, password)
        except LedgerError as exc:
            self.hint_var.set(exc.message)
            return
        self.hint_var.set("")
        self.on_success(user)


__all__ = ["LoginPanel"]

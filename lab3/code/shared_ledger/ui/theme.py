"""界面配色、字体与 ttk 样式。

配色沿用实验二 UI 原型的设计变量（``UI/ui.css``），让桌面界面与原型
处在同一套视觉语言下。所有样式都基于 Python 标准库自带的 ``clam``
主题派生，不引入任何第三方 UI 组件库。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# 设计变量（与实验二 ui.css 中的 :root 变量一一对应）
# ---------------------------------------------------------------------------
INK = "#101828"
INK2 = "#344054"
MUTED = "#667085"
FAINT = "#98a2b3"
LINE = "#e4e7ec"
APP_BG = "#f5f7fa"
CARD = "#ffffff"
BRAND = "#2f6fed"
BRAND_DARK = "#1d3f8f"
BRAND_DEEP = "#2559c9"
BRAND_SOFT = "#eaf1ff"
GREEN = "#067647"
GREEN_BG = "#ecfdf3"
RED = "#b42318"
RED_BG = "#fef3f2"
AMBER = "#b54708"
AMBER_BG = "#fffaeb"
PURPLE = "#5925dc"
PURPLE_BG = "#f4f3ff"
INDIGO = "#3538cd"
INDIGO_BG = "#eff4ff"
WHITE = "#ffffff"
SOFT_GRAY = "#f2f4f7"
TROUGH = "#eef1f6"

# 中文字体族，Windows 上优先使用微软雅黑
FONT = "Microsoft YaHei"

# 导航栏与页面尺寸
SIDEBAR_WIDTH = 236
WINDOW_SIZE = "1360x860"
WINDOW_MIN = (1180, 760)


def apply_theme(root: tk.Misc) -> None:
    """把统一样式应用到指定根窗口。

    :param root: 根窗口或任意 tkinter 容器。
    """
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", font=(FONT, 10), background=APP_BG, foreground=INK2)
    style.configure("TFrame", background=APP_BG)
    style.configure("Side.TFrame", background=CARD)
    style.configure("Card.TFrame", background=CARD)
    style.configure("Top.TFrame", background=CARD)
    style.configure("Status.TFrame", background=CARD)

    style.configure("TLabel", background=APP_BG, foreground=INK2)
    style.configure("Card.TLabel", background=CARD, foreground=INK2)
    style.configure("Top.TLabel", background=CARD, foreground=INK2)
    style.configure("Status.TLabel", background=CARD, foreground=MUTED)
    style.configure("Side.TLabel", background=CARD, foreground=INK2)
    style.configure("Muted.TLabel", background=APP_BG, foreground=MUTED)
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
    style.configure("Title.TLabel", background=APP_BG, foreground=INK, font=(FONT, 15, "bold"))
    style.configure("CardTitle.TLabel", background=CARD, foreground=INK, font=(FONT, 11, "bold"))
    style.configure("Sub.TLabel", background=APP_BG, foreground=MUTED, font=(FONT, 9))
    style.configure("CardSub.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
    style.configure("StatValue.TLabel", background=CARD, foreground=INK, font=(FONT, 17, "bold"))
    style.configure("StatLabel.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
    style.configure("StatSub.TLabel", background=CARD, foreground=MUTED, font=(FONT, 8))
    style.configure("Good.TLabel", background=CARD, foreground=GREEN, font=(FONT, 17, "bold"))
    style.configure("Bad.TLabel", background=CARD, foreground=RED, font=(FONT, 17, "bold"))
    style.configure("Warn.TLabel", background=CARD, foreground=AMBER, font=(FONT, 9))
    style.configure("Error.TLabel", background=APP_BG, foreground=RED, font=(FONT, 9))
    style.configure("Ok.TLabel", background=APP_BG, foreground=GREEN, font=(FONT, 9))
    style.configure("CardError.TLabel", background=CARD, foreground=RED, font=(FONT, 9))
    style.configure("CardOk.TLabel", background=CARD, foreground=GREEN, font=(FONT, 9))
    style.configure("CardWarn.TLabel", background=CARD, foreground=AMBER, font=(FONT, 9))

    style.configure("TButton", background=CARD, foreground=INK2, borderwidth=1, padding=(12, 6))
    style.map("TButton", background=[("active", SOFT_GRAY)])
    style.configure(
        "Primary.TButton", background=BRAND, foreground=WHITE, borderwidth=0, padding=(14, 7)
    )
    style.map("Primary.TButton", background=[("active", BRAND_DEEP), ("disabled", "#b2ccff")])
    style.configure("Danger.TButton", background=CARD, foreground=RED, bordercolor="#fda29b")
    style.map("Danger.TButton", background=[("active", RED_BG)])
    style.configure("Ghost.TButton", background=CARD, foreground=BRAND, borderwidth=0)
    style.map("Ghost.TButton", background=[("active", BRAND_SOFT)])
    style.configure(
        "Nav.TButton", background=CARD, foreground=INK2, anchor="w", padding=(16, 9),
        borderwidth=0
    )
    style.map(
        "Nav.TButton",
        background=[("active", BRAND_SOFT), ("selected", BRAND_SOFT)],
        foreground=[("selected", BRAND), ("active", BRAND)],
    )
    style.configure("NavActive.TButton", background=BRAND_SOFT, foreground=BRAND,
                    anchor="w", padding=(16, 9), borderwidth=0, font=(FONT, 10, "bold"))
    style.map("NavActive.TButton", background=[("active", BRAND_SOFT)])
    style.configure("Small.TButton", padding=(8, 4), font=(FONT, 9))

    style.configure(
        "TEntry", fieldbackground=WHITE, foreground=INK, bordercolor="#d0d5dd", padding=4
    )
    style.configure(
        "TCombobox", fieldbackground=WHITE, foreground=INK, bordercolor="#d0d5dd", padding=4
    )
    style.configure("TCheckbutton", background=CARD, foreground=INK2)
    style.configure("TRadiobutton", background=CARD, foreground=INK2)
    style.configure("Card.TCheckbutton", background=CARD, foreground=INK2)
    style.configure("Card.TRadiobutton", background=CARD, foreground=INK2)
    style.configure("TProgressbar", troughcolor=TROUGH, background=BRAND)
    style.configure("BudgetNormal.Horizontal.TProgressbar", troughcolor=TROUGH, background=BRAND)
    style.configure("BudgetWarn.Horizontal.TProgressbar", troughcolor=TROUGH, background="#f79009")
    style.configure("BudgetOver.Horizontal.TProgressbar", troughcolor=TROUGH, background="#f04438")
    style.configure("TSeparator", background=LINE)
    style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=INK2,
                    rowheight=27, borderwidth=0, font=(FONT, 9))
    style.map("Treeview", background=[("selected", BRAND_SOFT)], foreground=[("selected", INK)])
    style.configure("Treeview.Heading", background="#fcfcfd", foreground=MUTED,
                    font=(FONT, 9, "bold"), relief="flat", padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", SOFT_GRAY)])
    style.configure("TNotebook", background=APP_BG, borderwidth=0)


def tree_tags() -> dict:
    """返回表格行使用的颜色标签。

    :return: 标签名到前景色的映射。
    """
    return {
        "income": GREEN,
        "expense": INK,
        "muted": FAINT,
        "good": GREEN,
        "warn": AMBER,
        "bad": RED,
        "brand": BRAND,
    }


def apply_tree_tags(tree: ttk.Treeview) -> None:
    """为表格注册统一的行颜色标签。

    :param tree: 目标表格。
    """
    for name, color in tree_tags().items():
        tree.tag_configure(name, foreground=color)

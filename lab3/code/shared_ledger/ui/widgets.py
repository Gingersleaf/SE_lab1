"""界面通用组件、格式化工具与错误兜底。

本模块只放「与业务无关」的界面基础设施：卡片、表格、对话框、金额格式化
以及把业务异常转换成用户提示的装饰器。所有业务判断仍然留在业务服务里，
界面层不重复实现任何一条业务规则。
"""

# pylint: disable=broad-exception-caught  # 界面层必须兜底，单个页面出错不应带崩整个程序
# pylint: disable=too-many-arguments  # tkinter 控件工厂函数天然需要若干可选参数

from __future__ import annotations

import functools
import sqlite3
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Any, Callable, List, Optional, Sequence, Tuple

from ..domain.errors import LedgerError
from . import theme

#: 表格列定义：``(列标识, 表头文字, 列宽, 对齐方式)``。
ColumnSpec = Tuple[str, str, int, str]


# ---------------------------------------------------------------------------
# 数值与日期格式化
# ---------------------------------------------------------------------------
def format_money(value: Decimal) -> str:
    """把金额格式化为带货币符号的字符串。

    :param value: 金额。
    :return: 形如 ``¥1,234.56`` 的字符串。
    """
    return f"¥{Decimal(str(value)):,.2f}"


def format_amount(value: Decimal) -> str:
    """把金额格式化为不带货币符号的字符串。

    :param value: 金额。
    :return: 形如 ``1,234.56`` 的字符串。
    """
    return f"{Decimal(str(value)):,.2f}"


def format_signed(value: Decimal) -> str:
    """把带符号的金额格式化为字符串。

    :param value: 金额，正数带 ``+`` 号。
    :return: 形如 ``+1,234.56`` 的字符串。
    """
    number = Decimal(str(value))
    prefix = "+" if number > 0 else ""
    return f"{prefix}{number:,.2f}"


def parse_amount(text: str) -> Optional[Decimal]:
    """解析用户输入的金额。

    :param text: 输入文本。
    :return: 解析成功返回金额，否则返回 ``None``。
    """
    cleaned = (text or "").strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def parse_date(text: str) -> Optional[date]:
    """解析用户输入的日期。

    :param text: 输入文本，格式为 ``YYYY-MM-DD``。
    :return: 解析成功返回日期，否则返回 ``None``。
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError:
        return None


def month_range(back: int, end: Optional[date] = None) -> List[str]:
    """返回最近若干个月份字符串。

    :param back: 回溯的月份数。
    :param end: 结束日期，默认为今天。
    :return: 由早到晚的月份列表，格式为 ``YYYY-MM``。
    """
    moment = end or date.today()
    months: List[str] = []
    year, month = moment.year, moment.month
    for _ in range(max(1, back)):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    months.reverse()
    return months


def shift_month(month: str, offset: int) -> str:
    """把月份字符串前后平移若干个月。

    :param month: 月份字符串，格式为 ``YYYY-MM``。
    :param offset: 平移量，正数向后、负数向前。
    :return: 平移后的月份字符串。
    """
    year, mon = (int(part) for part in month.split("-"))
    total = year * 12 + (mon - 1) + offset
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def month_bounds(month: str) -> Tuple[date, date]:
    """返回某个月的第一天与最后一天。

    :param month: 月份字符串，格式为 ``YYYY-MM``。
    :return: ``(起始日期, 结束日期)``。
    """
    year, mon = (int(part) for part in month.split("-"))
    start = date(year, mon, 1)
    if mon == 12:
        end = date(year, 12, 31)
    else:
        end = date.fromordinal(date(year, mon + 1, 1).toordinal() - 1)
    return start, end


# ---------------------------------------------------------------------------
# 提示与对话框
# ---------------------------------------------------------------------------
def _parent_of(widget: Any) -> Optional[tk.Misc]:
    """取控件所属的顶层窗口。

    :param widget: 任意 tkinter 控件。
    :return: 顶层窗口，无法确定时返回 ``None``。
    """
    try:
        return widget.winfo_toplevel()
    except Exception:  # pragma: no cover - 仅在控件已销毁时触发
        return None


def show_error(widget: Any, message: str) -> None:
    """弹出错误提示框。

    :param widget: 触发错误的控件，用于定位父窗口。
    :param message: 面向用户的中文提示语。
    """
    messagebox.showerror("操作未完成", message, parent=_parent_of(widget))


def show_info(widget: Any, message: str, title: str = "提示") -> None:
    """弹出信息提示框。

    :param widget: 触发信息的控件。
    :param message: 提示内容。
    :param title: 提示框标题。
    """
    messagebox.showinfo(title, message, parent=_parent_of(widget))


def ask_reason(widget: Any, title: str, prompt: str, default: str = "") -> Optional[str]:
    """弹出原因输入对话框。

    驳回、作废、申诉等操作必须填写原因，这里统一收集。

    :param widget: 父控件。
    :param title: 对话框标题。
    :param prompt: 输入提示语。
    :param default: 输入框默认值。
    :return: 用户填写的原因；取消时返回 ``None``。
    """
    parent = _parent_of(widget)
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(False, False)
    frame = ttk.Frame(dialog, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=prompt, wraplength=380, justify="left").pack(anchor="w")
    entry = ttk.Entry(frame, width=42)
    entry.insert(0, default)
    entry.pack(fill="x", pady=(10, 4))
    ttk.Label(frame, text="原因不能为空（业务规则要求留痕）。", style="Muted.TLabel",
              font=(theme.FONT, 8)).pack(anchor="w")
    result: List[str] = []

    def confirm() -> None:
        """校验并关闭对话框。"""
        text = entry.get().strip()
        if not text:
            messagebox.showwarning("缺少原因", "请填写原因后再提交。", parent=dialog)
            return
        result.append(text)
        dialog.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(12, 0))
    ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="right")
    ttk.Button(buttons, text="确定", style="Primary.TButton", command=confirm).pack(
        side="right", padx=(0, 8)
    )
    entry.focus_set()
    entry.bind("<Return>", lambda _event: confirm())
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.update_idletasks()
    _center(dialog, parent)
    dialog.grab_set()
    dialog.wait_window()
    return result[0] if result else None


def _center(window: tk.Toplevel, parent: Optional[tk.Misc]) -> None:
    """把弹出窗口移动到父窗口中央。

    :param window: 弹出窗口。
    :param parent: 父窗口。
    """
    if parent is None:
        return
    try:
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - window.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - window.winfo_height()) // 3)
        window.geometry(f"+{x}+{y}")
    except Exception:  # pragma: no cover - 窗口尚未完成布局时忽略
        pass


def guard(func: Callable) -> Callable:
    """把业务异常转换成用户提示的装饰器。

    被装饰的方法在遇到 ``LedgerError`` 时弹出 ``exc.message``，
    遇到其它异常时给出统一的兜底提示，避免界面直接崩溃。

    :param func: 被装饰的方法。
    :return: 包装后的方法。
    """

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        """执行被装饰的方法并兜底异常。"""
        try:
            return func(self, *args, **kwargs)
        except LedgerError as exc:
            show_error(self, exc.message)
            return None
        except (sqlite3.Error, ValueError, ArithmeticError) as exc:
            show_error(self, f"数据处理失败：{exc}")
            return None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            show_error(self, f"操作失败：{exc}")
            return None

    return wrapper


# ---------------------------------------------------------------------------
# 基础控件工厂
# ---------------------------------------------------------------------------
def make_entry(parent: tk.Misc, width: int = 16, text: str = "") -> ttk.Entry:
    """创建输入框。

    :param parent: 父容器。
    :param width: 输入框宽度（字符数）。
    :param text: 初始内容。
    :return: 输入框控件。
    """
    entry = ttk.Entry(parent, width=width)
    if text:
        entry.insert(0, text)
    return entry


def make_combo(
    parent: tk.Misc, values: Sequence[str], width: int = 14, state: str = "readonly"
) -> ttk.Combobox:
    """创建下拉选择框。

    :param parent: 父容器。
    :param values: 可选值列表。
    :param width: 控件宽度（字符数）。
    :param state: 控件状态。
    :return: 下拉框控件。
    """
    combo = ttk.Combobox(parent, values=list(values), width=width, state=state)
    if values:
        combo.current(0)
    return combo


def make_button(
    parent: tk.Misc, text: str, command: Callable, style: str = "TButton"
) -> ttk.Button:
    """创建按钮。

    :param parent: 父容器。
    :param text: 按钮文字。
    :param command: 点击回调。
    :param style: ttk 样式名。
    :return: 按钮控件。
    """
    return ttk.Button(parent, text=text, command=command, style=style)


# ---------------------------------------------------------------------------
# 卡片与表格
# ---------------------------------------------------------------------------
class Card(ttk.Frame):
    """白色卡片容器，自带标题、副标题与内容区。"""

    def __init__(
        self,
        master: tk.Misc,
        title: str = "",
        subtitle: str = "",
        **kwargs: Any,
    ) -> None:
        """初始化卡片。

        :param master: 父容器。
        :param title: 卡片标题。
        :param subtitle: 卡片副标题。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, style="Card.TFrame", **kwargs)
        self.header = ttk.Frame(self, style="Card.TFrame")
        self.header.pack(fill="x", padx=16, pady=(14, 0))
        if title:
            ttk.Label(self.header, text=title, style="CardTitle.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(self.header, text=subtitle, style="CardSub.TLabel").pack(anchor="w")
        self.body = ttk.Frame(self, style="Card.TFrame")
        self.body.pack(fill="both", expand=True, padx=16, pady=14)


class StatCard(Card):
    """统计卡片：标题 + 数值 + 补充说明。"""

    def __init__(self, master: tk.Misc, label: str, **kwargs: Any) -> None:
        """初始化统计卡片。

        :param master: 父容器。
        :param label: 卡片标题。
        :param kwargs: 透传给 ``Card`` 的参数。
        """
        super().__init__(master, **kwargs)
        ttk.Label(self.body, text=label, style="StatLabel.TLabel").pack(anchor="w")
        self.value_label = ttk.Label(self.body, text="—", style="StatValue.TLabel")
        self.value_label.pack(anchor="w", pady=(6, 0))
        self.sub_label = ttk.Label(self.body, text="", style="StatSub.TLabel")
        self.sub_label.pack(anchor="w", pady=(4, 0))

    def set_value(self, text: str, tone: str = "normal") -> None:
        """设置数值与配色。

        :param text: 数值文字。
        :param tone: ``normal``、``good`` 或 ``bad``。
        """
        style = {"normal": "StatValue.TLabel", "good": "Good.TLabel", "bad": "Bad.TLabel"}
        self.value_label.configure(text=text, style=style.get(tone, "StatValue.TLabel"))

    def set_sub(self, text: str) -> None:
        """设置补充说明。

        :param text: 说明文字。
        """
        self.sub_label.configure(text=text)


def make_table(
    parent: tk.Misc,
    columns: Sequence[ColumnSpec],
    height: int = 10,
    selectmode: str = "browse",
) -> Tuple[ttk.Frame, ttk.Treeview]:
    """创建带纵向滚动条的表格。

    :param parent: 父容器。
    :param columns: 列定义列表。
    :param height: 可见行数。
    :param selectmode: 选择模式。
    :return: ``(容器, 表格)``。
    """
    holder = ttk.Frame(parent)
    holder.rowconfigure(0, weight=1)
    holder.columnconfigure(0, weight=1)
    tree = ttk.Treeview(
        holder,
        columns=[item[0] for item in columns],
        show="headings",
        height=height,
        selectmode=selectmode,
    )
    for key, heading, width, anchor in columns:
        tree.heading(key, text=heading)
        tree.column(key, width=width, anchor=anchor, stretch=anchor == "w")
    scrollbar = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")
    theme.apply_tree_tags(tree)
    return holder, tree


def set_rows(tree: ttk.Treeview, rows: Sequence[Tuple[Sequence[Any], Sequence[str]]]) -> None:
    """用给定数据整体替换表格内容。

    :param tree: 目标表格。
    :param rows: ``(各列取值, 行标签)`` 组成的列表。
    """
    children = tree.get_children()
    if children:
        tree.delete(*children)
    for values, tags in rows:
        tree.insert("", "end", values=tuple(values), tags=tuple(tags))


def bind_row_menu(
    tree: ttk.Treeview,
    column_key: str,
    provider: Callable[[str], List[Tuple[str, Callable[[], None]]]],
) -> None:
    """让表格的指定列支持点击弹出操作菜单。

    :param tree: 目标表格。
    :param column_key: 触发菜单的列标识。
    :param provider: 根据行标识返回 ``(菜单文字, 回调)`` 列表的函数。
    """
    index = tree["columns"].index(column_key) + 1
    target = f"#{index}"

    def on_click(event: tk.Event) -> None:
        """在操作列上弹出菜单。"""
        if tree.identify_column(event.x) != target:
            return
        row = tree.identify_row(event.y)
        if not row:
            return
        items = provider(row)
        if not items:
            return
        menu = tk.Menu(tree, tearoff=0)
        for label, command in items:
            menu.add_command(label=label, command=command)
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    tree.bind("<Button-1>", on_click)


class ScrollFrame(tk.Frame):
    """可纵向滚动的容器，用于承载不定高的列表。"""

    def __init__(self, master: tk.Misc, **kwargs: Any) -> None:
        """初始化滚动容器。

        :param master: 父容器。
        :param kwargs: 透传给 ``tk.Frame`` 的参数。
        """
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=theme.APP_BG)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="TFrame")
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        for widget in (self.canvas, self.inner):
            widget.bind("<MouseWheel>", self._on_wheel)

    def _on_inner_configure(self, _event: tk.Event) -> None:
        """内容变化时更新滚动区域。"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        """容器尺寸变化时同步内部宽度。"""
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_wheel(self, event: tk.Event) -> None:
        """响应鼠标滚轮。"""
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class LedgerPage(ttk.Frame):
    """账本内功能页面的基类。

    页面通过 ``app`` 取得当前登录用户与当前账本，所有取数都经由
    ``ApplicationContext`` 中的业务服务完成。
    """

    def __init__(self, master: tk.Misc, app: Any, **kwargs: Any) -> None:
        """初始化页面。

        :param master: 父容器。
        :param app: 主窗口对象。
        :param kwargs: 透传给 ``ttk.Frame`` 的参数。
        """
        super().__init__(master, **kwargs)
        self.app = app
        self.context = app.context

    @property
    def ledger_id(self) -> str:
        """返回当前账本标识。"""
        return self.app.current_ledger_id

    @property
    def user_id(self) -> str:
        """返回当前登录用户标识。"""
        return self.app.user.user_id

    def refresh(self) -> None:
        """刷新页面数据，默认什么也不做。"""


class TrendChart(tk.Canvas):
    """最近若干个月的收支柱状图。"""

    def __init__(self, master: tk.Misc, **kwargs: Any) -> None:
        """初始化图表。

        :param master: 父容器。
        :param kwargs: 透传给 ``tk.Canvas`` 的参数。
        """
        super().__init__(
            master, background=theme.CARD, height=140, highlightthickness=0, **kwargs
        )
        self._points: List[Tuple[str, Decimal, Decimal]] = []

    def set_points(self, points: Sequence[Tuple[str, Decimal, Decimal]]) -> None:
        """设置数据点并重绘。

        :param points: ``(月份, 收入, 支出)`` 组成的列表。
        """
        self._points = list(points)
        self.draw()

    def draw(self) -> None:
        """按当前数据重绘图表。"""
        self.delete("all")
        width = max(self.winfo_width(), 320)
        height = max(self.winfo_height(), 140)
        bottom = height - 26
        top = 14
        if not self._points:
            self.create_text(width / 2, height / 2, text="暂无统计数据", fill=theme.MUTED)
            return
        peak = max(
            [
                float(value)
                for _month, income, expense in self._points
                for value in (income, expense)
            ]
            + [1.0]
        )
        slots = len(self._points)
        slot = width / slots
        bar_width = min(26, slot / 3)
        for index, (month, income, expense) in enumerate(self._points):
            center = slot * index + slot / 2
            for offset, value, color in (
                (-bar_width, income, theme.GREEN),
                (bar_width, expense, theme.BRAND),
            ):
                bar_height = (float(value) / peak) * (bottom - top)
                left_edge = center + offset - bar_width / 2
                right_edge = center + offset + bar_width / 2
                top_edge = bottom - bar_height
                self.create_rectangle(
                    left_edge, top_edge, right_edge, bottom, fill=color, outline=color
                )
                if bar_height > 14:
                    self.create_text(
                        (left_edge + right_edge) / 2,
                        top_edge - 8,
                        text=f"{float(value):,.0f}",
                        fill=theme.MUTED,
                        font=(theme.FONT, 8),
                    )
            self.create_text(
                center, bottom + 13, text=month[5:] + "月", fill=theme.MUTED, font=(theme.FONT, 8)
            )
        self.create_text(
            10, 8, text="■ 支出", fill=theme.BRAND, anchor="nw", font=(theme.FONT, 8)
        )
        self.create_text(
            62, 8, text="■ 收入", fill=theme.GREEN, anchor="nw", font=(theme.FONT, 8)
        )

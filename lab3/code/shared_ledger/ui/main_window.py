"""主窗口：登录、导航、账本切换与页面调度。

主窗口是界面层的总入口，负责：

1. 装配应用上下文并在数据库为空时灌入演示数据；
2. 登录成功后搭建左侧导航、顶部账本切换器与内容区；
3. 在各个功能页面之间调度切换，并在关闭时释放数据库连接。
"""

# pylint: disable=attribute-defined-outside-init  # tkinter 控件在多层构建方法中创建，属于构造过程的一部分

# pylint: disable=too-many-instance-attributes  # 主窗口需要持有导航、页面与登录态等大量引用

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional

from ..app import ApplicationContext
from ..demo import run_demo
from ..domain.entities import LedgerMember, User
from ..domain.enums import Role
from ..domain.errors import LedgerError
from ..service.ledger_member_service import LedgerSummary
from . import theme
from .audit_page import AuditPage
from .budget_page import BudgetPage
from .category_page import CategoryPage
from .log_page import LogPage
from .login_panel import LoginPanel
from .member_page import MemberPage
from .overview_page import OverviewPage
from .record_detail_page import RecordDetailPage
from .record_form_page import RecordFormPage
from .records_page import RecordsPage
from .settlement_page import SettlementPage
from .widgets import LedgerPage, show_error

#: 导航项：``(页面键, 显示文字, 所属分组)``。
NAV_ITEMS = (
    ("overview", "账本概览", "账本"),
    ("records", "收支记录", "账本"),
    ("audit", "待审核", "账本"),
    ("settlement", "结算单", "账本"),
    ("member", "成员", "设置"),
    ("category", "分类", "设置"),
    ("budget", "预算", "设置"),
    ("log", "操作日志", "设置"),
)

#: 页面键与页面类的对应关系。
PAGE_CLASSES = {
    "overview": OverviewPage,
    "records": RecordsPage,
    "audit": AuditPage,
    "settlement": SettlementPage,
    "member": MemberPage,
    "category": CategoryPage,
    "budget": BudgetPage,
    "log": LogPage,
    "record_form": RecordFormPage,
    "record_detail": RecordDetailPage,
}

#: 各角色可查询的范围说明。
SCOPE_TEXT = {
    Role.ADMIN: "可查询全账本统计、成员、分类、预算与全部操作日志。",
    Role.WRITER: "可查询账本统计与记录；操作日志仅限与自己相关的条目。",
    Role.READER: "仅可查看统计与记录，不能修改任何内容，操作日志查询受限。",
}


class MainWindow(tk.Frame):
    """应用主窗口。

    既可以自己创建一个 ``tk.Tk`` 根窗口（``MainWindow(context)``），
    也可以嵌入调用方已经建好的根窗口（``MainWindow(root, context)``），
    便于在测试脚本中把界面挂到既有窗口上。
    """

    def __init__(
        self,
        master: Any = None,
        context: Optional[ApplicationContext] = None,
        **kwargs: Any,
    ) -> None:
        """初始化主窗口。

        :param master: 父窗口；缺省时自建一个 ``tk.Tk`` 根窗口。
            也可以直接把 ``ApplicationContext`` 传进来，此时自动自建根窗口。
        :param context: 应用上下文，缺省时按内存数据库新建一个。
        :param kwargs: 透传给 ``tk.Frame`` 的参数。
        """
        owns_root = False
        if isinstance(master, ApplicationContext):
            master, context = None, master
        if master is None:
            master = tk.Tk()
            owns_root = True
        super().__init__(master, **kwargs)
        self.pack(fill="both", expand=True)
        self.owns_root = owns_root
        self.context = context if context is not None else ApplicationContext()
        self.user: Optional[User] = None
        self.member: Optional[LedgerMember] = None
        self.ledger_summaries: List[LedgerSummary] = []
        self.current_ledger_id = ""
        self.pages: Dict[str, LedgerPage] = {}
        self.nav_buttons: Dict[str, ttk.Button] = {}
        self.content: Optional[ttk.Frame] = None
        self._context_closed = False

        self.master.title("多人共享记账系统 · 软件工程实验三")
        self.master.geometry(theme.WINDOW_SIZE)
        self.master.minsize(*theme.WINDOW_MIN)
        theme.apply_theme(self)
        self._build_login()
        self.master.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------------
    # 登录阶段
    # ------------------------------------------------------------------
    def _build_login(self) -> None:
        """搭建登录界面。"""
        self.login_panel = LoginPanel(self, self.context, self._on_login)
        self.login_panel.pack(fill="both", expand=True)

    def _on_login(self, user: User) -> None:
        """登录成功后的处理。

        :param user: 登录用户。
        """
        self.user = user
        self.ledger_summaries = self.context.members.list_ledgers_for_user(user.user_id)
        if not self.ledger_summaries:
            show_error(self, "该账号还没有加入任何账本，请先通过管理员的邀请链接加入。")
            return
        self.current_ledger_id = self.ledger_summaries[0].ledger.ledger_id
        self.login_panel.destroy()
        self._build_shell()

    # ------------------------------------------------------------------
    # 主界面
    # ------------------------------------------------------------------
    def _build_shell(self) -> None:
        """搭建左侧导航、顶部栏与内容区。"""
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(1, weight=1)
        self._build_sidebar(shell)
        main = ttk.Frame(shell)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(1, weight=1)
        main.columnconfigure(0, weight=1)
        self._build_topbar(main)
        self.content = ttk.Frame(main)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self._build_statusbar(main)
        self._refresh_identity()
        self.show_page("overview")

    def _build_sidebar(self, shell: ttk.Frame) -> None:
        """搭建左侧导航栏。

        :param shell: 主容器。
        """
        sidebar = ttk.Frame(shell, style="Side.TFrame", width=theme.SIDEBAR_WIDTH)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(1, weight=1)

        brand = ttk.Frame(sidebar, style="Side.TFrame")
        brand.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            brand, text="账", style="Side.TLabel", font=(theme.FONT, 15, "bold"),
            background=theme.BRAND, foreground=theme.WHITE, width=3
        ).grid(row=0, column=0, sticky="w", padx=(16, 8), pady=(16, 0))
        ttk.Label(
            brand, text="多人共享记账系统", style="Side.TLabel", font=(theme.FONT, 11, "bold")
        ).grid(row=0, column=1, sticky="w", pady=(18, 0))
        self.ledger_info = ttk.Label(brand, text="", style="Side.TLabel")
        self.ledger_info.grid(row=1, column=1, sticky="w", pady=(2, 16))

        nav = ttk.Frame(sidebar, style="Side.TFrame")
        nav.grid(row=1, column=0, sticky="nsew")
        group = ""
        row_index = 0
        for key, text, section in NAV_ITEMS:
            if section != group:
                group = section
                ttk.Label(
                    nav, text=section, style="Side.TLabel",
                    foreground=theme.FAINT, font=(theme.FONT, 9)
                ).grid(row=row_index, column=0, sticky="w", padx=18, pady=(14, 4))
                row_index += 1
            button = ttk.Button(
                nav, text=text, style="Nav.TButton", command=lambda k=key: self.show_page(k)
            )
            button.grid(row=row_index, column=0, sticky="ew")
            self.nav_buttons[key] = button
            row_index += 1

        footer = ttk.Frame(sidebar, style="Side.TFrame")
        footer.grid(row=2, column=0, sticky="ew")
        ttk.Separator(footer, orient="horizontal").pack(fill="x")
        ttk.Label(
            footer, text="当前身份", style="Side.TLabel",
            foreground=theme.FAINT, font=(theme.FONT, 9)
        ).pack(anchor="w", padx=18, pady=(10, 0))
        self.identity_label = ttk.Label(footer, text="", style="Side.TLabel")
        self.identity_label.pack(anchor="w", padx=18)
        self.scope_label = ttk.Label(
            footer, text="", style="Side.TLabel", foreground=theme.MUTED,
            wraplength=200, justify="left", font=(theme.FONT, 8)
        )
        self.scope_label.pack(anchor="w", padx=18, pady=(4, 16))

    def _build_topbar(self, main: ttk.Frame) -> None:
        """搭建顶部栏。

        :param main: 主内容容器。
        """
        top = ttk.Frame(main, style="Top.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="当前账本", style="Top.TLabel").pack(side="left", padx=(20, 8))
        self.ledger_combo = ttk.Combobox(
            top,
            values=[item.ledger.name for item in self.ledger_summaries],
            state="readonly",
            width=18,
        )
        self.ledger_combo.current(0)
        self.ledger_combo.pack(side="left")
        self.ledger_combo.bind("<<ComboboxSelected>>", self._on_ledger_changed)
        ttk.Button(top, text="+ 记一笔", style="Primary.TButton",
                   command=self.open_record_form).pack(side="right", padx=(0, 20), pady=12)
        self.user_label = ttk.Label(top, text="", style="Top.TLabel")
        self.user_label.pack(side="right", padx=(0, 10))
        self.avatar = ttk.Label(
            top, text="", style="Top.TLabel", background=theme.BRAND_SOFT,
            foreground=theme.INDIGO, width=3, font=(theme.FONT, 10, "bold")
        )
        self.avatar.pack(side="right")

    def _build_statusbar(self, main: ttk.Frame) -> None:
        """搭建底部状态栏。

        :param main: 主内容容器。
        """
        status_bar = ttk.Frame(main, style="Status.TFrame")
        status_bar.grid(row=2, column=0, sticky="ew")
        self.status_label = ttk.Label(status_bar, text="就绪", style="Status.TLabel")
        self.status_label.pack(side="left", padx=20, pady=6)
        self.db_label = ttk.Label(
            status_bar, text=self.context.database.path, style="Status.TLabel"
        )
        self.db_label.pack(side="right", padx=20, pady=6)

    # ------------------------------------------------------------------
    # 状态刷新
    # ------------------------------------------------------------------
    def _refresh_identity(self) -> None:
        """刷新侧栏身份信息与顶部用户信息。"""
        member = self.context.members.member_of(self.current_ledger_id, self.user.user_id)
        self.member = member
        role = member.role if member is not None else Role.READER
        name = self.user.display_name
        self.identity_label.configure(text=f"{name} · {role.display_name}")
        self.scope_label.configure(text=SCOPE_TEXT.get(role, ""))
        self.user_label.configure(text=f"{name} · {role.display_name}")
        self.avatar.configure(text=name[:1])
        summary = self._current_summary()
        if summary is not None:
            self.ledger_info.configure(
                text=f"{summary.member_count} 位成员 · {summary.pending_count} 条待审核"
            )

    def _current_summary(self) -> Optional[LedgerSummary]:
        """返回当前账本的汇总信息。

        :return: 账本汇总；找不到时返回 ``None``。
        """
        for item in self.ledger_summaries:
            if item.ledger.ledger_id == self.current_ledger_id:
                return item
        return None

    def _on_ledger_changed(self, _event: object = None) -> None:
        """切换账本。"""
        index = self.ledger_combo.current()
        if 0 <= index < len(self.ledger_summaries):
            self.current_ledger_id = self.ledger_summaries[index].ledger.ledger_id
        self._refresh_identity()
        self.refresh_all()
        self.status(f"已切换到账本：{self.ledger_combo.get()}")

    def refresh_all(self) -> None:
        """刷新全部已创建页面。"""
        for page in self.pages.values():
            page.refresh()
        self._refresh_identity()

    def status(self, message: str) -> None:
        """在状态栏显示一条提示。

        :param message: 提示文字。
        """
        self.status_label.configure(text=message)

    # ------------------------------------------------------------------
    # 页面调度
    # ------------------------------------------------------------------
    def show_page(self, key: str) -> None:
        """切换到指定页面。

        :param key: 页面键。
        """
        page = self.pages.get(key)
        if page is None:
            page_class = PAGE_CLASSES.get(key)
            if page_class is None:
                return
            page = page_class(self.content, self)
            page.grid(row=0, column=0, sticky="nsew", padx=24, pady=20)
            self.pages[key] = page
        for name, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if name == key else "Nav.TButton")
        try:
            page.refresh()
        except LedgerError as exc:
            show_error(self, exc.message)
        page.tkraise()
        self.status(f"当前页面：{self._page_title(key)}")

    @staticmethod
    def _page_title(key: str) -> str:
        """返回页面键对应的中文标题。

        :param key: 页面键。
        :return: 标题文字。
        """
        for name, text, _section in NAV_ITEMS:
            if name == key:
                return text
        return {"record_form": "记一笔", "record_detail": "记录详情"}.get(key, key)

    def open_record_detail(self, record_id: str) -> None:
        """打开记录详情页。

        :param record_id: 记录标识。
        """
        page = self._ensure_page("record_detail")
        page.open_detail(record_id)
        self.show_page("record_detail")

    def open_record_form(self, record_id: str = "") -> None:
        """打开记一笔页面。

        :param record_id: 待编辑的记录标识，空字符串表示新建。
        """
        page = self._ensure_page("record_form")
        page.open_form(record_id)
        self.show_page("record_form")

    def _ensure_page(self, key: str) -> LedgerPage:
        """确保指定页面已创建。

        :param key: 页面键。
        :return: 页面实例。
        """
        page = self.pages.get(key)
        if page is None:
            page_class = PAGE_CLASSES[key]
            page = page_class(self.content, self)
            page.grid(row=0, column=0, sticky="nsew", padx=24, pady=20)
            self.pages[key] = page
        return page

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------
    def close(self) -> None:
        """关闭窗口并释放数据库连接。"""
        try:
            if not self._context_closed:
                self._context_closed = True
                self.context.close()
        finally:
            try:
                self.destroy()
            finally:
                if self.owns_root:
                    self.master.destroy()

    def mainloop(self) -> None:
        """进入事件循环。"""
        self.master.mainloop()


def ensure_seed_data(context: ApplicationContext) -> bool:
    """数据库为空时灌入演示数据。

    :param context: 应用上下文。
    :return: 是否执行了演示数据灌入。
    """
    if context.auth.list_users():
        return False
    run_demo(context)
    return True


def launch(db_path: str) -> None:
    """启动桌面界面。

    :param db_path: 数据库文件路径。
    """
    context = ApplicationContext(db_path)
    try:
        ensure_seed_data(context)
        window = MainWindow(context=context)
        window.mainloop()
    finally:
        context.close()


__all__ = ["MainWindow", "launch", "ensure_seed_data"]

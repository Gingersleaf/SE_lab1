"""图形界面截图脚本。

用于给实验报告准备运行截图：启动桌面界面、自动登录到指定页面、
保持窗口若干秒后退出，配合系统的屏幕截图能力即可得到报告里的界面图。

用法::

    python tools/capture_gui.py --page overview --seconds 12 --db capture.db

``--page`` 可选值与界面左侧导航的键一致，例如
``overview``（账本概览）、``records``（收支记录）、``audit``（待审核）、
``settlement``（结算单）、``member``（成员）、``category``（分类）、
``budget``（预算）、``log``（操作日志）。
"""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared_ledger.app import ApplicationContext  # noqa: E402
from shared_ledger.ui.main_window import MainWindow, ensure_seed_data  # noqa: E402

DEMO_ACCOUNT = "zhoucy"
DEMO_PASSWORD = "123456"


def main() -> int:
    """启动界面并保持指定时长。

    :return: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="图形界面截图辅助脚本")
    parser.add_argument("--page", default="overview", help="启动后直接进入的页面")
    parser.add_argument("--seconds", type=int, default=12, help="保持窗口的秒数")
    parser.add_argument("--db", default="capture_gui.db", help="数据库文件路径")
    parser.add_argument("--width", type=int, default=1440, help="窗口宽度")
    parser.add_argument("--height", type=int, default=900, help="窗口高度")
    parser.add_argument(
        "--rect", default="window_rect.txt", help="窗口位置输出文件，供外部按区域截图"
    )
    args = parser.parse_args()

    context = ApplicationContext(args.db)
    ensure_seed_data(context)
    root = tk.Tk()
    root.title("多人共享记账系统")
    root.geometry(f"{args.width}x{args.height}")
    root.attributes("-topmost", True)

    window = MainWindow(root, context)
    window.pack(fill="both", expand=True)

    def enter_main_view() -> None:
        """自动登录并跳到指定页面。"""
        try:
            user = context.auth.login(DEMO_ACCOUNT, DEMO_PASSWORD)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"自动登录失败：{exc}")
            root.destroy()
            return
        window._on_login(user)  # pylint: disable=protected-access
        window.show_page(args.page)
        window.status(f"已以 {user.display_name} 身份登录，当前页面：{args.page}")

    def write_rect() -> None:
        """把窗口在屏幕上的位置写入文件，供外部按窗口区域截图。"""
        root.update_idletasks()
        root.lift()
        root.focus_force()
        rect = (
            f"{root.winfo_rootx()},{root.winfo_rooty()},"
            f"{root.winfo_width()},{root.winfo_height()}"
        )
        Path(args.rect).write_text(rect, encoding="utf-8")

    root.after(600, enter_main_view)
    root.after(1500, write_rect)
    root.after(args.seconds * 1000, root.destroy)
    root.mainloop()
    context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

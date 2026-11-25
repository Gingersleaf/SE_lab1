"""命令行入口。

用法::

    python -m shared_ledger.cli demo            # 运行端到端演示场景
    python -m shared_ledger.cli demo --db demo.db
    python -m shared_ledger.cli ui --db shared_ledger.db   # 启动桌面界面

命令行入口与图形界面共用同一套业务服务，
演示场景也是图形界面的初始数据来源，三者不会出现行为不一致。
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .app import ApplicationContext
from .demo import run_demo


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。

    :return: 参数解析器。
    """
    parser = argparse.ArgumentParser(
        prog="shared-ledger", description="多人共享记账系统"
    )
    subparsers = parser.add_subparsers(dest="command")

    demo_parser = subparsers.add_parser(
        "demo", help="运行端到端演示场景并输出每一步结果"
    )
    demo_parser.add_argument(
        "--db", default=":memory:", help="数据库文件路径，默认使用内存数据库"
    )

    ui_parser = subparsers.add_parser("ui", help="启动 tkinter 桌面界面")
    ui_parser.add_argument(
        "--db", default="shared_ledger.db", help="数据库文件路径"
    )

    subparsers.add_parser("version", help="显示版本号")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """命令行主入口。

    :param argv: 命令行参数列表，默认为 ``sys.argv[1:]``。
    :return: 进程退出码。
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "demo"

    if command == "version":
        print(f"shared-ledger {__version__}")
        return 0

    if command == "ui":
        # 图形界面模块只在真正要启动界面时才导入，
        # 这样命令行模式不必加载 tkinter，也让两种启动方式互不影响
        # pylint: disable=import-outside-toplevel
        from .ui import launch

        launch(args.db)
        return 0

    context = ApplicationContext(args.db)
    try:
        result = run_demo(context, echo=print)
    finally:
        context.close()
    failed = [step for step in result.steps if not step.result]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

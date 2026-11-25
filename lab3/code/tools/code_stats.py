"""代码规模统计脚本。

按实验三任务书的要求统计「实现的软件代码量」，并区分三类来源：

1. 手写业务代码（domain / support / persistence / service）—— 这是任务书
   要求计入的核心实现；
2. 表现层代码（ui）—— 任务书说明「基于 GUI 设计工具自动生成的代码
   不算在内」，本项目的界面是手写的，但为保守起见单独列出、不计入；
3. 测试代码（tests）—— 单独列出，供「设计单元测试」这一项佐证。

统计口径：只统计非空且非注释行（代码行），并另列总行数与注释行数。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List


def count_file(path: Path) -> Dict[str, int]:
    """统计单个文件的行数。

    :param path: 文件路径。
    :return: 含总行数、代码行数与注释行数的字典。
    """
    total = 0
    code = 0
    comment = 0
    in_doc = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        total += 1
        line = raw.strip()
        if in_doc:
            comment += 1
            if line.endswith('"""') or line.endswith("'''"):
                in_doc = False
            continue
        if not line:
            continue
        if line.startswith('"""') or line.startswith("'''"):
            comment += 1
            if not (len(line) > 3 and (line.endswith('"""') or line.endswith("'''"))):
                in_doc = True
            continue
        if line.startswith("#"):
            comment += 1
            continue
        code += 1
    return {"total": total, "code": code, "comment": comment}


def count_tree(root: Path, patterns: List[str]) -> Dict[str, Dict[str, int]]:
    """统计目录下匹配的文件。

    :param root: 根目录。
    :param patterns: 文件名匹配模式列表。
    :return: 键为相对路径、值为行数统计的字典。
    """
    result: Dict[str, Dict[str, int]] = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if "__pycache__" in path.parts:
                continue
            result[str(path.relative_to(root)).replace("\\", "/")] = count_file(path)
    return result


def summarize(files: Dict[str, Dict[str, int]]) -> Dict[str, int]:
    """汇总一组文件的行数。

    :param files: 文件行数统计。
    :return: 汇总结果。
    """
    return {
        "files": len(files),
        "total": sum(item["total"] for item in files.values()),
        "code": sum(item["code"] for item in files.values()),
        "comment": sum(item["comment"] for item in files.values()),
    }


def main() -> int:
    """执行统计并输出结果。

    :return: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="统计代码规模")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--json", default="", help="把结果写入 JSON 文件")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    groups = {
        "domain（领域层）": count_tree(root / "shared_ledger/domain", ["*.py"]),
        "support（支撑层）": count_tree(root / "shared_ledger/support", ["*.py"]),
        "persistence（数据层）": count_tree(root / "shared_ledger/persistence", ["*.py"]),
        "service（业务层）": count_tree(root / "shared_ledger/service", ["*.py"]),
        "表现层与入口": count_tree(
            root / "shared_ledger",
            ["app.py", "cli.py", "demo.py", "__init__.py", "ui/*.py"],
        ),
        "tests（测试）": count_tree(root / "tests", ["*.py"]),
    }

    print("=" * 72)
    print("多人共享记账系统 · 代码规模统计")
    print("=" * 72)
    print(f"{'模块':<24}{'文件数':>8}{'总行数':>10}{'代码行':>10}{'注释行':>10}")
    print("-" * 72)
    grand = {"files": 0, "total": 0, "code": 0, "comment": 0}
    core = {"files": 0, "total": 0, "code": 0, "comment": 0}
    for name, files in groups.items():
        stat = summarize(files)
        for key in grand:
            grand[key] += stat[key]
        print(
            f"{name:<24}{stat['files']:>8}{stat['total']:>10}"
            f"{stat['code']:>10}{stat['comment']:>10}"
        )
        if name != "tests（测试）":
            for key in core:
                core[key] += stat[key]
    print("-" * 72)
    print(
        f"{'合计':<24}{grand['files']:>8}{grand['total']:>10}"
        f"{grand['code']:>10}{grand['comment']:>10}"
    )
    print()
    print(f"任务书口径（不含表现层与测试的核心实现）：{core['code']} 行代码")
    print(f"含表现层与测试的全部手写代码：{grand['code']} 行")
    print("=" * 72)

    if args.json:
        payload = {
            "groups": {name: summarize(files) for name, files in groups.items()},
            "grand_total": grand,
            "core_implementation": core,
            "files": {
                name: files for name, files in groups.items()
            },
        }
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

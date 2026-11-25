"""把 UML 类图更新到与实验三的实现一致。

实验二类图上没有画出、但实现必需的字段（口令散列、审核留痕、快照标识、
展示用冗余字段等），在本脚本中补进类图，使 UML 与代码一一对应。
"""

import pathlib
import sys

TARGET = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None

ADDITIONS = {
    "User": ["    -passwordHash: string", "    -createdAt: datetime"],
    "LedgerMember": ["    -displayName: string", "    -accountName: string"],
    "Invitation": ["    -maxUses: int"],
    "Record": ["    -reviewedAt: datetime", "    -reviewerId: UUID"],
    "RecordTrace": ["    -actorName: string"],
    "Category": ["    -recordCount: int"],
    "StatResult": ["    -label: string"],
    "Settlement": ["    -snapshotRecordIds: list"],
    "SettlementMember": ["    -memberName: string"],
    "TransferPlanItem": ["    -fromMemberName: string", "    -toMemberName: string"],
    "OperationLog": ["    -actorName: string"],
}


def main() -> int:
    """执行类图字段补全。

    :return: 进程退出码。
    """
    if TARGET is None:
        print("usage: update_class_diagram.py <UML类图.puml>")
        return 2
    lines = TARGET.read_text(encoding="utf-8").split("\n")
    result = []
    current = None
    pending = dict(ADDITIONS)
    for line in lines:
        result.append(line)
        if line.startswith("class "):
            current = line.split()[1].split(" as ")[0].strip()
        if current and line.strip() == "}" and current in pending:
            extra = pending.pop(current)
            # 回退到该类的起始行，把新字段插在类体开头
            start = len(result) - 2
            while start >= 0 and not result[start].startswith("class "):
                start -= 1
            result[start + 1 : start + 1] = extra
    TARGET.write_text("\n".join(result), encoding="utf-8")
    print("updated, remaining:", list(pending))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

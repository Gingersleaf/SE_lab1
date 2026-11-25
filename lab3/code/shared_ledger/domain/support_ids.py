"""标识生成工具。

系统中的标识分两类：

- 全局唯一标识（用户、账本、记录、成员等实体主键）使用 UUID4，
  不依赖任何中心节点，离线生成也不会冲突。
- 业务编号（记录号、结算单号、日志号）使用「前缀-日期-序号」形式，
  便于人工在界面上口头指代某一条记录，实验二 UI 原型中也是这种形态。

序号在同一进程内自增，日期取当天。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from threading import Lock

_COUNTERS: dict = {}
_COUNTER_LOCK = Lock()


def new_uuid() -> str:
    """生成一个 UUID4 字符串。

    :return: 32 位十六进制字符串。
    """
    return uuid.uuid4().hex


def new_sequential_id(prefix: str, width: int = 4, now: datetime = None) -> str:
    """生成业务编号。

    :param prefix: 编号前缀，例如 ``R``、``ST``、``L``。
    :param width: 序号位数。
    :param now: 时间，默认为当前时间。
    :return: 形如 ``R-20261103-0001`` 的编号。
    """
    moment = now or datetime.now()
    key = f"{prefix}-{moment.strftime('%Y%m%d')}"
    with _COUNTER_LOCK:
        current = _COUNTERS.get(key, 0) + 1
        _COUNTERS[key] = current
    return f"{key}-{current:0{width}d}"


def new_settlement_id(now: datetime = None) -> str:
    """生成结算单编号。

    :param now: 时间，默认为当前时间。
    :return: 形如 ``ST-2026-11-001`` 的编号。
    """
    moment = now or datetime.now()
    key = f"ST-{moment.strftime('%Y-%m')}"
    with _COUNTER_LOCK:
        current = _COUNTERS.get(key, 0) + 1
        _COUNTERS[key] = current
    return f"{key}-{current:03d}"


def reset_counters() -> None:
    """重置序号计数器，仅供单元测试使用。"""
    with _COUNTER_LOCK:
        _COUNTERS.clear()

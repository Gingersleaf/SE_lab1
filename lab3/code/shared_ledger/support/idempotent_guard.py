"""幂等去重。

对应实验二组件图中的支撑模块组件 `IdempotentGuard`。

对应 REQ-035：客户端每次新增记录附带唯一请求标识，服务端按该标识去重，
标识在服务端保留七天；七天内重复提交同一标识时返回首次提交的结果，
不产生第二条记录；超过七天的标识按新请求正常处理。

这个组件被单独抽出来的原因是它横跨表现层与业务层：
表现层负责生成请求标识，服务层负责登记与查重，
两边各写一份很容易出现「标识格式不一致导致去重失效」。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Protocol

from ..domain.entities import RequestDedup


class DedupStore(Protocol):
    """幂等记录存储的协议定义。

    抽象成协议而不是直接依赖仓储类，是为了让本组件可以被单元测试替换成
    内存实现，也避免支撑层与持久层产生反向依赖。
    """

    def find_active(self, request_id: str, now: datetime) -> Optional[object]:
        """返回仍在保留期内的幂等记录，不存在时返回 ``None``。"""

    def save(self, dedup_record: object) -> None:
        """保存一条幂等记录。"""

    def purge_expired(self, now: datetime) -> int:
        """删除已过期的幂等记录，返回删除条数。"""


class IdempotentGuard:
    """幂等去重组件。"""

    RETENTION_DAYS = 7

    def __init__(self, store: DedupStore) -> None:
        """初始化幂等守卫。

        :param store: 幂等记录存储。
        """
        self._store = store

    @property
    def retention(self) -> timedelta:
        """返回幂等标识的保留时长。"""
        return timedelta(days=self.RETENTION_DAYS)

    def lookup(self, request_id: str, now: datetime) -> Optional[str]:
        """查找请求标识对应的首次结果。

        :param request_id: 客户端生成的请求标识。
        :param now: 当前时间。
        :return: 首次产生的记录标识；标识不存在或已过期时返回 ``None``。
        """
        if not request_id:
            return None
        found = self._store.find_active(request_id, now)
        if found is None:
            return None
        expire_at = getattr(found, "expire_at", None)
        if expire_at is not None and expire_at <= now:
            return None
        result_record_id = getattr(found, "result_record_id", "")
        return result_record_id or None

    def remember(
        self, request_id: str, user_id: str, record_id: str, now: datetime
    ) -> None:
        """登记一次请求标识与结果的对应关系。

        :param request_id: 客户端生成的请求标识。
        :param user_id: 发起请求的用户。
        :param record_id: 本次请求产生的记录标识。
        :param now: 当前时间。
        """
        if not request_id:
            return
        self._store.save(self._build(request_id, user_id, record_id, now))

    def purge_expired(self, now: datetime) -> int:
        """清理已过期的幂等记录。

        :param now: 当前时间。
        :return: 删除的记录条数。
        """
        return self._store.purge_expired(now)

    @staticmethod
    def _build(request_id: str, user_id: str, record_id: str, now: datetime) -> object:
        """构造幂等记录实体。

        :param request_id: 请求标识。
        :param user_id: 发起用户。
        :param record_id: 产生的记录标识。
        :param now: 当前时间。
        :return: 幂等记录实体。
        """
        return RequestDedup(
            request_id=request_id,
            user_id=user_id,
            result_record_id=record_id,
            created_at=now,
            expire_at=now + IdempotentGuard.RETENTION_DAYS * timedelta(days=1),
        )

"""操作日志服务。

对应实验二组件图中的操作日志模块 `LogService`。

两条硬约束：

1. 日志只增不改不删（REQ-040）。本模块不提供任何更新或删除日志的方法，
   仓储层同样只提供追加与查询。
2. 日志写入失败时关键操作整体回滚（REQ-039）。关键操作与其日志写在
   同一个事务里，由 ``Database.transaction()`` 收口。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List, Optional

from ..domain.entities import OperationLog
from ..domain.enums import LogActionType
from ..domain.errors import PermissionDeniedError
from ..domain.support_ids import new_sequential_id
from ..persistence.repositories import Page, RepositoryRegistry
from .access import AccessGuard


class LogService:
    """操作日志服务。"""

    def __init__(self, repos: RepositoryRegistry, access: AccessGuard) -> None:
        """初始化日志服务。

        :param repos: 仓储集合。
        :param access: 权限守卫，用于判定日志可见范围。
        """
        self._repos = repos
        self._access = access

    def append(
        self,
        ledger_id: str,
        actor_id: str,
        action: LogActionType,
        target_type: str,
        target_id: str,
        params: str = "",
        occurred_at: Optional[datetime] = None,
    ) -> OperationLog:
        """追加一条操作日志。

        :param ledger_id: 账本标识。
        :param actor_id: 操作者标识。
        :param action: 操作类型。
        :param target_type: 操作对象类型。
        :param target_id: 操作对象标识。
        :param params: 关键参数。
        :param occurred_at: 发生时间，默认为当前时间。
        :return: 写入的日志实体。
        """
        log = OperationLog(
            log_id=self._new_log_id(),
            ledger_id=ledger_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            params=params,
            occurred_at=occurred_at or datetime.now(),
        )
        self._repos.logs.save(log)
        return log

    def append_params(
        self,
        ledger_id: str,
        actor_id: str,
        action: LogActionType,
        target_type: str,
        target_id: str,
        payload: Any,
    ) -> OperationLog:
        """以结构化参数追加一条日志。

        :param ledger_id: 账本标识。
        :param actor_id: 操作者标识。
        :param action: 操作类型。
        :param target_type: 操作对象类型。
        :param target_id: 操作对象标识。
        :param payload: 可序列化的关键参数。
        :return: 写入的日志实体。
        """
        return self.append(
            ledger_id,
            actor_id,
            action,
            target_type,
            target_id,
            json.dumps(payload, ensure_ascii=False, default=str),
        )

    def append_denial(self, error: Exception) -> Optional[OperationLog]:
        """为一次越权拒绝补写日志。

        本方法在关键操作的事务回滚之后调用，因此不会随操作一起回滚。

        :param error: 越权异常。
        :return: 写入的日志实体，缺少账本上下文时返回 ``None``。
        """
        ledger_id = getattr(error, "ledger_id", "")
        if not ledger_id:
            return None
        target_type = getattr(error, "target_type", "") or "UNKNOWN"
        target_id = getattr(error, "target_id", "") or ""
        detail = getattr(error, "detail", "") or str(error)
        actor_id = getattr(error, "actor_id", "")
        member = self._repos.members.find(ledger_id, actor_id)
        if member is not None:
            actor_id = member.member_id
        return self.append(
            ledger_id,
            actor_id,
            LogActionType.ACCESS_DENIED,
            target_type,
            target_id,
            detail,
        )

    def query(
        self,
        actor_user_id: str,
        ledger_id: str,
        action: Optional[LogActionType] = None,
        actor_member_id: str = "",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        keyword: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> Page:
        """查询操作日志。

        管理员可查询本账本的全部日志；记账成员只能查询与自己相关的日志；
        只读成员的可见范围在需求分析阶段标记为待确认（REQ-041），
        这里按用例图 UC016 只授予记账成员的保守口径处理，
        只读成员查询日志会被拒绝并留痕。

        :param actor_user_id: 查询者。
        :param ledger_id: 账本标识。
        :param action: 按操作类型过滤。
        :param actor_member_id: 按操作人过滤。
        :param start: 起始时间。
        :param end: 结束时间。
        :param keyword: 关键字，匹配参数文本。
        :param page: 页码。
        :param page_size: 每页条数。
        :return: 分页结果。
        """
        member = self._access.require_member(ledger_id, actor_user_id)
        if member.role.can_manage_member:
            logs = self._repos.logs.list_by_ledger(ledger_id)
        elif member.role.can_write_record:
            logs = self._repos.logs.list_by_actor(ledger_id, member.member_id)
        else:
            error = PermissionDeniedError(
                "没有执行该操作的权限",
                "只读成员无权查询操作日志",
                ledger_id=ledger_id,
                actor_id=actor_user_id,
                target_type="操作日志",
                target_id=member.member_id,
            )
            self.append_denial(error)
            raise error

        filtered = self._filter(logs, action, actor_member_id, start, end, keyword)
        filtered.sort(key=lambda item: item.occurred_at, reverse=True)
        size = min(max(1, int(page_size)), 500)
        current = max(1, int(page))
        offset = (current - 1) * size
        return Page(
            items=filtered[offset : offset + size],
            total=len(filtered),
            page=current,
            page_size=size,
        )

    @staticmethod
    def _filter(
        logs: List[OperationLog],
        action: Optional[LogActionType],
        actor_member_id: str,
        start: Optional[datetime],
        end: Optional[datetime],
        keyword: str,
    ) -> List[OperationLog]:
        """按条件过滤日志列表。

        :param logs: 原始日志列表。
        :param action: 操作类型。
        :param actor_member_id: 操作人标识。
        :param start: 起始时间。
        :param end: 结束时间。
        :param keyword: 关键字。
        :return: 过滤后的日志列表。
        """
        result: List[OperationLog] = []
        for log in logs:
            if action is not None and log.action is not action:
                continue
            if actor_member_id and log.actor_id != actor_member_id:
                continue
            if start is not None and log.occurred_at < start:
                continue
            if end is not None and log.occurred_at > end:
                continue
            if keyword and keyword not in log.params and keyword not in log.target_id:
                continue
            result.append(log)
        return result

    @staticmethod
    def _new_log_id() -> str:
        """生成日志编号。

        :return: 形如 ``L-20261103-0001`` 的日志编号。
        """
        return new_sequential_id("L")

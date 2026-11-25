"""业务服务公共基类。

服务层的两个公共机制放在这里：

1. ``with_denial_log`` 装饰器：越权异常在关键操作的事务回滚之后补写日志，
   保证「越权被拒绝」这件事一定留痕（REQ-044），同时不会因为
   业务事务回滚把越权痕迹一起抹掉。
2. ``BaseService``：统一持有仓储、权限守卫与日志服务三个公共依赖。
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from ..domain.errors import PermissionDeniedError
from ..persistence.repositories import RepositoryRegistry
from .access import AccessGuard


def with_denial_log(func: Callable) -> Callable:
    """为服务方法补写越权日志。

    :param func: 被装饰的服务方法。
    :return: 包装后的方法。
    """

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return func(self, *args, **kwargs)
        except PermissionDeniedError as exc:
            logs = getattr(self, "logs", None)
            if logs is not None:
                logs.append_denial(exc)
            raise

    return wrapper


class BaseService:
    """业务服务基类。"""

    def __init__(
        self, repos: RepositoryRegistry, access: AccessGuard, logs: Any = None
    ) -> None:
        """初始化服务。

        :param repos: 仓储集合。
        :param access: 权限守卫。
        :param logs: 日志服务，部分服务不需要写日志时可以不传。
        """
        self.repos = repos
        self.access = access
        self.logs = logs

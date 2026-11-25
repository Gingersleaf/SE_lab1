"""乐观锁版本校验。

对应实验二组件图中的支撑模块组件 `OptimisticLock`。

对应 REQ-037：记录保存时携带该记录的版本号，版本号与当前记录版本不一致时
拒绝保存并提示记录已被他人修改，要求用户刷新后重新编辑；
系统不得以静默覆盖的方式处理冲突。

单独成组件的原因与幂等去重相同：它是横切规则，被记录服务、
冲正流程与结算快照共同依赖。
"""

from __future__ import annotations

from ..domain.errors import VersionConflictError


class OptimisticLock:
    """乐观锁版本校验组件。"""

    @staticmethod
    def assert_version(expected_version: int, current_version: int) -> None:
        """校验客户端持有的版本号是否与当前版本一致。

        :param expected_version: 客户端持有的版本号。
        :param current_version: 服务端当前记录的版本号。
        :raises VersionConflictError: 两个版本号不一致。
        """
        if expected_version is None:
            return
        if int(expected_version) != int(current_version):
            raise VersionConflictError()

    @staticmethod
    def next_version(current_version: int) -> int:
        """返回下一个版本号。

        :param current_version: 当前版本号。
        :return: 递增一后的版本号。
        """
        return int(current_version) + 1

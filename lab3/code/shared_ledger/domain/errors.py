"""业务异常体系。

把各类业务失败拆成明确的异常类型，而不是一律抛 ``RuntimeError``，
目的是让调用方（表现层）能够针对不同失败原因给出不同的提示语，
同时让单元测试可以按异常类型断言，而不是匹配错误字符串。

每个异常都带一个稳定的 ``code``，用于日志记录与接口返回。
"""

from __future__ import annotations


class LedgerError(Exception):
    """所有业务异常的基类。

    业务异常表示「请求本身合法，但当前业务条件不满足」，
    与程序缺陷引发的 ``Exception`` 区分开，便于上层统一兜底。
    """

    code = "LEDGER_ERROR"

    def __init__(self, message: str, detail: str = "") -> None:
        """初始化业务异常。

        :param message: 面向用户的中文提示语。
        :param detail: 补充说明，仅用于日志与调试，不直接展示。
        """
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        """返回提示语。"""
        return self.message


class ValidationError(LedgerError):
    """数据校验失败。

    覆盖金额取值与精度（REQ-017）、单笔上限（REQ-018）、
    分摊合计一致性（REQ-020）等在保存前就必须拦截的问题。
    """

    code = "VALIDATION_ERROR"


class PermissionDeniedError(LedgerError):
    """越权操作被拒绝。

    对应 REQ-044 最小权限原则：任何超出角色权限范围的作一律拒绝，
    并且必须留下可审计的越权日志，不允许静默丢弃。

    异常上带着账本、操作者与目标对象的上下文，
    由服务层的统一包装器在事务回滚之后补写越权日志，
    这样既不会出现「越权被拒但没有留痕」，也不会出现
    「操作回滚了但越权日志也跟着丢了」。
    """

    code = "PERMISSION_DENIED"

    def __init__(
        self,
        message: str,
        detail: str = "",
        *,
        ledger_id: str = "",
        actor_id: str = "",
        target_type: str = "",
        target_id: str = "",
    ) -> None:
        """初始化越权异常。

        :param message: 面向用户的中文提示语。
        :param detail: 补充说明。
        :param ledger_id: 发生越权操作的账本。
        :param actor_id: 尝试越权的操作者。
        :param target_type: 被操作的对象类型。
        :param target_id: 被操作的对象标识。
        """
        super().__init__(message, detail)
        self.ledger_id = ledger_id
        self.actor_id = actor_id
        self.target_type = target_type
        self.target_id = target_id


class StateConflictError(LedgerError):
    """状态冲突。

    对应 REQ-036：以先到先得的操作为准，后到的操作被拒绝并提示
    「记录状态已变更，请刷新」。
    """

    code = "STATE_CONFLICT"

    def __init__(self, message: str, detail: str = "") -> None:
        """初始化状态冲突异常。

        :param message: 面向用户的中文提示语。
        :param detail: 补充说明。
        """
        super().__init__(message or "记录状态已变更，请刷新", detail)


class VersionConflictError(LedgerError):
    """乐观锁版本冲突。

    对应 REQ-037：版本号不一致时拒绝保存并提示记录已被他人修改，
    不允许以静默覆盖的方式处理冲突。
    """

    code = "VERSION_CONFLICT"

    def __init__(self, message: str = "记录已被他人修改，请刷新后重新编辑") -> None:
        """初始化版本冲突异常。

        :param message: 面向用户的中文提示语。
        """
        super().__init__(message)


class IdempotencyConflictError(LedgerError):
    """幂等键冲突。

    对应 REQ-035：同一请求标识在保留期内重复提交时返回首次结果；
    当首次请求仍在处理中、结果尚不可用时抛出本异常。
    """

    code = "IDEMPOTENCY_CONFLICT"


class NotFoundError(LedgerError):
    """对象不存在。

    查询或操作的目标对象在数据库中不存在，或不属于当前账本。
    """

    code = "NOT_FOUND"


class BusinessRuleError(LedgerError):
    """业务规则不满足。

    用于表达「既不是参数非法、也不是权限或状态问题，但依然不允许执行」
    的规则，例如账本内没有可参与结算的记录、邀请链接已过期。
    """

    code = "BUSINESS_RULE_ERROR"

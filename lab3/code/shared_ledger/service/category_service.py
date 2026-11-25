"""分类服务。

对应实验二组件图中的分类模块 `CategoryService`。

覆盖 REQ-021：已被使用过的分类不可删除，只能停用；
停用后该分类不能再被新记录选用，历史记录中的该分类不受影响。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List

from ..domain.entities import Category
from ..domain.enums import CategoryStatus, LogActionType
from ..domain.errors import BusinessRuleError, ValidationError
from ..domain.support_ids import new_uuid
from ..persistence.repositories import RepositoryRegistry
from .base import BaseService, with_denial_log


class CategoryService(BaseService):
    """分类服务。"""

    def __init__(
        self, repos: RepositoryRegistry, access: Any, logs: Any = None
    ) -> None:
        """初始化服务。

        :param repos: 仓储集合。
        :param access: 权限守卫。
        :param logs: 日志服务。
        """
        super().__init__(repos, access, logs)

    @with_denial_log
    def list_categories(
        self, actor_user_id: str, ledger_id: str
    ) -> List[Category]:
        """列出账本内全部分类。

        :param actor_user_id: 操作者，必须是账本成员。
        :param ledger_id: 账本标识。
        :return: 分类列表。
        """
        self.access.require_reader(ledger_id, actor_user_id)
        categories = self.repos.categories.list_by_ledger(ledger_id)
        for item in categories:
            item.record_count = self.repos.categories.count_usage(item.category_id)
        return categories

    @with_denial_log
    def create_category(
        self, actor_user_id: str, ledger_id: str, name: str
    ) -> Category:
        """新建一个自建分类。

        :param actor_user_id: 操作者，必须是记账成员或管理员。
        :param ledger_id: 账本标识。
        :param name: 分类名称。
        :return: 新建的分类。
        :raises ValidationError: 名称为空、超长或与已有分类重名。
        """
        member = self.access.require_writer(ledger_id, actor_user_id)
        text = (name or "").strip()
        if not text:
            raise ValidationError("分类名称不能为空")
        if len(text) > 12:
            raise ValidationError("分类名称过长")
        if self.repos.categories.find_by_name(ledger_id, text) is not None:
            raise ValidationError("同名分类已存在")

        category = Category(
            category_id=new_uuid(),
            ledger_id=ledger_id,
            name=text,
            is_default=False,
            status=CategoryStatus.ENABLED,
            created_at=datetime.now(),
        )
        self.repos.categories.save(category)
        self.logs.append_params(
            ledger_id,
            member.member_id,
            LogActionType.RECORD_SUBMIT,
            "分类",
            category.category_id,
            {"操作": "新建分类", "名称": category.name},
        )
        return category

    @with_denial_log
    def disable_category(
        self, actor_user_id: str, ledger_id: str, category_id: str
    ) -> Category:
        """停用一个分类。

        停用后该分类不能被新记录选用，历史记录仍显示原分类名称。

        :param actor_user_id: 操作者，必须是记账成员或管理员。
        :param ledger_id: 账本标识。
        :param category_id: 分类标识。
        :return: 更新后的分类。
        :raises BusinessRuleError: 分类不存在或已被停用。
        """
        member = self.access.require_writer(ledger_id, actor_user_id)
        category = self._require_category(ledger_id, category_id)
        if category.status is CategoryStatus.DISABLED:
            raise BusinessRuleError("该分类已经是停用状态")
        category.status = CategoryStatus.DISABLED
        self.repos.categories.save(category)
        self.logs.append_params(
            ledger_id,
            member.member_id,
            LogActionType.RECORD_SUBMIT,
            "分类",
            category.category_id,
            {"操作": "停用分类", "名称": category.name},
        )
        return category

    @with_denial_log
    def delete_category(
        self, actor_user_id: str, ledger_id: str, category_id: str
    ) -> None:
        """删除一个尚未被使用过的分类。

        :param actor_user_id: 操作者，必须是记账成员或管理员。
        :param ledger_id: 账本标识。
        :param category_id: 分类标识。
        :raises BusinessRuleError: 分类不存在或已被记录使用。
        """
        member = self.access.require_writer(ledger_id, actor_user_id)
        category = self._require_category(ledger_id, category_id)
        usage = self.repos.categories.count_usage(category_id)
        if usage > 0:
            raise BusinessRuleError("该分类已被记录使用，只能停用不能删除")
        self.repos.categories.delete(category_id)
        self.logs.append_params(
            ledger_id,
            member.member_id,
            LogActionType.RECORD_SUBMIT,
            "分类",
            category_id,
            {"操作": "删除分类", "名称": category.name},
        )

    def _require_category(self, ledger_id: str, category_id: str) -> Category:
        """查找分类并校验其属于指定账本。

        :param ledger_id: 账本标识。
        :param category_id: 分类标识。
        :return: 分类实体。
        :raises BusinessRuleError: 分类不存在。
        """
        category = self.repos.categories.find_by_id(category_id)
        if category is None or category.ledger_id != ledger_id:
            raise BusinessRuleError("分类不存在")
        return category

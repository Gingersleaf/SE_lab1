"""账号与登录服务。

实验一 REQ-001 的前置条件写明「操作用户处于登录状态」，因此实现需要
一个最小的账号体系。需求分析阶段没有对账号体系展开细化，
这里只实现支撑本版本所需的最小集合：注册、登录、修改口令。

口令不以明文保存，而是用 PBKDF2-HMAC-SHA256 加随机盐派生后存储。
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import List, Optional

from ..domain.entities import User
from ..domain.errors import NotFoundError, ValidationError
from ..domain.support_ids import new_uuid
from ..persistence.repositories import RepositoryRegistry

SALT_BYTES = 16
HASH_ITERATIONS = 120000


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """计算口令散列。

    :param password: 明文口令。
    :param salt: 随机盐，默认为新生成。
    :return: 形如 ``pbkdf2$<salt>$<hash>`` 的散列串。
    """
    if salt is None:
        salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, HASH_ITERATIONS
    )
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验口令是否正确。

    :param password: 明文口令。
    :param stored: 数据库中保存的散列串。
    :return: 校验通过时返回 ``True``。
    """
    try:
        _, salt_hex, digest_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
    except (ValueError, AttributeError):
        return False
    expected = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, HASH_ITERATIONS
    )
    return hmac.compare_digest(expected.hex(), digest_hex)


class AuthService:
    """账号与登录服务。"""

    def __init__(self, repos: RepositoryRegistry) -> None:
        """初始化认证服务。

        :param repos: 仓储集合。
        """
        self.repos = repos

    def register(
        self, account_name: str, display_name: str, password: str
    ) -> User:
        """注册一个新账号。

        :param account_name: 账号名，全局唯一。
        :param display_name: 昵称。
        :param password: 口令。
        :return: 新建的用户实体。
        :raises ValidationError: 账号名重复或参数不合法。
        """
        name = (account_name or "").strip()
        if not name:
            raise ValidationError("账号名不能为空")
        if len(name) > 32:
            raise ValidationError("账号名过长")
        if len(password or "") < 6:
            raise ValidationError("口令长度至少 6 位")
        if self.repos.users.find_by_account(name) is not None:
            raise ValidationError("账号名已存在")

        user = User(
            user_id=new_uuid(),
            account_name=name,
            display_name=(display_name or name).strip(),
            status="ACTIVE",
            password_hash=hash_password(password),
        )
        self.repos.users.save(user)
        return user

    def login(self, account_name: str, password: str) -> User:
        """登录账号。

        :param account_name: 账号名。
        :param password: 口令。
        :return: 登录成功的用户实体。
        :raises NotFoundError: 账号不存在或口令不正确。
        """
        user = self.repos.users.find_by_account((account_name or "").strip())
        if user is None or not verify_password(password or "", user.password_hash):
            raise NotFoundError("账号或口令不正确")
        if not user.is_active:
            raise NotFoundError("账号已被停用")
        return user

    def get_user(self, user_id: str) -> User:
        """按标识查找用户。

        :param user_id: 用户标识。
        :return: 用户实体。
        :raises NotFoundError: 用户不存在。
        """
        user = self.repos.users.find_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        return user

    def change_password(
        self, user_id: str, old_password: str, new_password: str
    ) -> User:
        """修改口令。

        :param user_id: 用户标识。
        :param old_password: 原口令。
        :param new_password: 新口令。
        :return: 更新后的用户实体。
        :raises ValidationError: 原口令不正确或新口令不合法。
        """
        user = self.get_user(user_id)
        if not verify_password(old_password or "", user.password_hash):
            raise ValidationError("原口令不正确")
        if len(new_password or "") < 6:
            raise ValidationError("口令长度至少 6 位")
        user.password_hash = hash_password(new_password)
        self.repos.users.save(user)
        return user

    def list_users(self) -> List[User]:
        """列出全部账号，供演示与测试使用。"""
        return self.repos.users.list_all()

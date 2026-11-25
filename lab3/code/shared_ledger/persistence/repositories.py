"""实体仓储。

数据访问层对业务层只暴露「按领域语言组织的读写方法」，
SQL 语句集中在本模块，避免散落在各业务服务里。

金额一律以字符串存入 TEXT 列，读出时再转回 ``Decimal``，
用 TEXT 而不是 REAL 是为了避免二进制浮点误差在结算环节累积。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional, Sequence

from ..domain.entities import (
    Budget,
    Category,
    Invitation,
    Ledger,
    LedgerMember,
    OperationLog,
    Record,
    RecordTrace,
    RequestDedup,
    Settlement,
    SettlementMember,
    ShareItem,
    TransferPlanItem,
    User,
)
from ..domain.enums import (
    CategoryStatus,
    InvitationStatus,
    LogActionType,
    MemberStatus,
    RecordStatus,
    RecordType,
    Role,
    SettlementStatus,
)


def _dt(value: Optional[str]) -> Optional[datetime]:
    """把 ISO 时间字符串转成 ``datetime``。

    :param value: ISO 字符串，可能为 ``None``。
    :return: 解析结果。
    """
    return datetime.fromisoformat(value) if value else None


def _dec(value: Any) -> Decimal:
    """把数据库中的金额文本转成 ``Decimal``。

    :param value: 数据库取值。
    :return: 金额值，空值按零处理。
    """
    return Decimal(str(value)) if value not in (None, "") else Decimal("0.00")


@dataclass
class RecordFilter:
    """记录多条件查询条件，对应 REQ-023。

    各条件之间是「并且」关系，翻页时条件保持不变。
    """

    record_type: Optional[RecordType] = None
    category_id: Optional[str] = None
    member_id: Optional[str] = None
    status: Optional[RecordStatus] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    amount_min: Optional[Decimal] = None
    amount_max: Optional[Decimal] = None
    keyword: str = ""
    page: int = 1
    page_size: int = 20

    def normalized(self) -> "RecordFilter":
        """返回页码与页长合法化后的副本。

        :return: 合法化的查询条件。
        """
        page = max(1, int(self.page))
        size = min(max(1, int(self.page_size)), 200)
        return RecordFilter(
            record_type=self.record_type,
            category_id=self.category_id,
            member_id=self.member_id,
            status=self.status,
            date_from=self.date_from,
            date_to=self.date_to,
            amount_min=self.amount_min,
            amount_max=self.amount_max,
            keyword=self.keyword,
            page=page,
            page_size=size,
        )


@dataclass
class Page:
    """分页查询结果。"""

    items: List[Any] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20

    @property
    def page_count(self) -> int:
        """返回总页数。"""
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size


class BaseRepository:
    """仓储基类，统一持有数据库连接。"""

    def __init__(self, database: Any) -> None:
        """初始化仓储。

        :param database: 数据库封装。
        """
        self._db = database

    @property
    def connection(self) -> sqlite3.Connection:
        """返回数据库连接。"""
        return self._db.connection

    def _query(self, sql: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
        """执行查询。

        :param sql: 查询语句。
        :param params: 绑定参数。
        :return: 结果行列表。
        """
        cursor = self.connection.execute(sql, tuple(params))
        try:
            return cursor.fetchall()
        finally:
            cursor.close()

    def _one(self, sql: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        """执行只返回一行的查询。

        :param sql: 查询语句。
        :param params: 绑定参数。
        :return: 结果行或 ``None``。
        """
        cursor = self.connection.execute(sql, tuple(params))
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        """执行写入语句。

        处于显式事务中时不立即提交，由事务上下文统一收口，
        保证关键操作与其日志要么一起成功、要么一起回滚（REQ-039）。

        :param sql: 写入语句。
        :param params: 绑定参数。
        """
        self.connection.execute(sql, tuple(params))
        if not self._db.in_transaction:
            self.connection.commit()


class UserRepository(BaseRepository):
    """用户仓储。"""

    def save(self, user: User) -> None:
        """保存或更新用户。"""
        self._execute(
            """
            INSERT INTO users (user_id, account_name, display_name, status,
                               password_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                account_name = excluded.account_name,
                display_name = excluded.display_name,
                status = excluded.status,
                password_hash = excluded.password_hash
            """,
            (
                user.user_id,
                user.account_name,
                user.display_name,
                user.status,
                user.password_hash,
                user.created_at.isoformat(),
            ),
        )

    def find_by_id(self, user_id: str) -> Optional[User]:
        """按标识查找用户。"""
        row = self._one("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return self._to_user(row) if row else None

    def find_by_account(self, account_name: str) -> Optional[User]:
        """按账号名查找用户。"""
        row = self._one(
            "SELECT * FROM users WHERE account_name = ?", (account_name,)
        )
        return self._to_user(row) if row else None

    def list_all(self) -> List[User]:
        """列出全部用户。"""
        return [self._to_user(row) for row in self._query("SELECT * FROM users")]

    @staticmethod
    def _to_user(row: sqlite3.Row) -> User:
        """把结果行转换为用户实体。"""
        return User(
            user_id=row["user_id"],
            account_name=row["account_name"],
            display_name=row["display_name"],
            status=row["status"],
            password_hash=row["password_hash"],
            created_at=_dt(row["created_at"]),
        )


class LedgerRepository(BaseRepository):
    """账本仓储。"""

    def save(self, ledger: Ledger) -> None:
        """保存或更新账本。"""
        self._execute(
            """
            INSERT INTO ledgers (ledger_id, name, admin_member_id, created_at,
                                member_limit, record_limit)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ledger_id) DO UPDATE SET
                name = excluded.name,
                admin_member_id = excluded.admin_member_id
            """,
            (
                ledger.ledger_id,
                ledger.name,
                ledger.admin_member_id,
                ledger.created_at.isoformat(),
                ledger.member_limit,
                ledger.record_limit,
            ),
        )

    def find_by_id(self, ledger_id: str) -> Optional[Ledger]:
        """按标识查找账本。"""
        row = self._one("SELECT * FROM ledgers WHERE ledger_id = ?", (ledger_id,))
        return self._to_ledger(row) if row else None

    def list_all(self) -> List[Ledger]:
        """列出全部账本。"""
        return [self._to_ledger(row) for row in self._query("SELECT * FROM ledgers")]

    @staticmethod
    def _to_ledger(row: sqlite3.Row) -> Ledger:
        """把结果行转换为账本实体。"""
        return Ledger(
            ledger_id=row["ledger_id"],
            name=row["name"],
            admin_member_id=row["admin_member_id"],
            created_at=_dt(row["created_at"]),
            member_limit=row["member_limit"],
            record_limit=row["record_limit"],
        )


class LedgerMemberRepository(BaseRepository):
    """账本成员仓储。"""

    def save(self, member: LedgerMember) -> None:
        """保存或更新成员。"""
        self._execute(
            """
            INSERT INTO ledger_members (member_id, user_id, ledger_id, role, status,
                                        joined_at, settlement_eligible)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(member_id) DO UPDATE SET
                role = excluded.role,
                status = excluded.status,
                settlement_eligible = excluded.settlement_eligible
            """,
            (
                member.member_id,
                member.user_id,
                member.ledger_id,
                member.role.value,
                member.status.value,
                member.joined_at.isoformat(),
                int(member.settlement_eligible),
            ),
        )

    def find_by_id(self, member_id: str) -> Optional[LedgerMember]:
        """按标识查找成员。"""
        row = self._one("SELECT * FROM ledger_members WHERE member_id = ?", (member_id,))
        return self._to_member(row) if row else None

    def find(self, ledger_id: str, user_id: str) -> Optional[LedgerMember]:
        """按账本与用户查找成员。"""
        row = self._one(
            "SELECT * FROM ledger_members WHERE ledger_id = ? AND user_id = ?",
            (ledger_id, user_id),
        )
        return self._to_member(row) if row else None

    def list_by_ledger(self, ledger_id: str) -> List[LedgerMember]:
        """列出账本内全部成员，按加入时间升序。"""
        rows = self._query(
            """
            SELECT m.*, u.display_name AS display_name, u.account_name AS account_name
            FROM ledger_members m
            JOIN users u ON u.user_id = m.user_id
            WHERE m.ledger_id = ?
            ORDER BY m.joined_at ASC
            """,
            (ledger_id,),
        )
        return [self._to_member(row) for row in rows]

    def list_by_user(self, user_id: str) -> List[LedgerMember]:
        """列出用户参与的全部账本成员关系。"""
        rows = self._query(
            """
            SELECT m.*, u.display_name AS display_name, u.account_name AS account_name
            FROM ledger_members m
            JOIN users u ON u.user_id = m.user_id
            WHERE m.user_id = ?
            ORDER BY m.joined_at ASC
            """,
            (user_id,),
        )
        return [self._to_member(row) for row in rows]

    def count_active(self, ledger_id: str) -> int:
        """统计账本内仍在册的成员数。"""
        row = self._one(
            "SELECT COUNT(*) AS total FROM ledger_members "
            "WHERE ledger_id = ? AND status = ?",
            (ledger_id, MemberStatus.ACTIVE.value),
        )
        return int(row["total"]) if row else 0

    @staticmethod
    def _to_member(row: sqlite3.Row) -> LedgerMember:
        """把结果行转换为成员实体。"""
        keys = row.keys()
        return LedgerMember(
            member_id=row["member_id"],
            user_id=row["user_id"],
            ledger_id=row["ledger_id"],
            role=Role(row["role"]),
            status=MemberStatus(row["status"]),
            joined_at=_dt(row["joined_at"]),
            settlement_eligible=bool(row["settlement_eligible"]),
            display_name=row["display_name"] if "display_name" in keys else "",
            account_name=row["account_name"] if "account_name" in keys else "",
        )


class InvitationRepository(BaseRepository):
    """邀请仓储。"""

    def save(self, invitation: Invitation) -> None:
        """保存或更新邀请。"""
        self._execute(
            """
            INSERT INTO invitations (invitation_id, token, ledger_id, issuer_member_id,
                                     invite_role, status, expires_at, used_count,
                                     max_uses, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(invitation_id) DO UPDATE SET
                status = excluded.status,
                used_count = excluded.used_count,
                expires_at = excluded.expires_at
            """,
            (
                invitation.invitation_id,
                invitation.token,
                invitation.ledger_id,
                invitation.issuer_member_id,
                invitation.invite_role.value,
                invitation.status.value,
                invitation.expires_at.isoformat(),
                invitation.used_count,
                invitation.max_uses,
                invitation.created_at.isoformat(),
            ),
        )

    def find_by_id(self, invitation_id: str) -> Optional[Invitation]:
        """按标识查找邀请。"""
        row = self._one(
            "SELECT * FROM invitations WHERE invitation_id = ?", (invitation_id,)
        )
        return self._to_invitation(row) if row else None

    def find_by_token(self, token: str) -> Optional[Invitation]:
        """按令牌查找邀请。"""
        row = self._one("SELECT * FROM invitations WHERE token = ?", (token,))
        return self._to_invitation(row) if row else None

    def list_by_ledger(self, ledger_id: str) -> List[Invitation]:
        """列出账本内的全部邀请。"""
        rows = self._query(
            "SELECT * FROM invitations WHERE ledger_id = ? ORDER BY created_at DESC",
            (ledger_id,),
        )
        return [self._to_invitation(row) for row in rows]

    @staticmethod
    def _to_invitation(row: sqlite3.Row) -> Invitation:
        """把结果行转换为邀请实体。"""
        return Invitation(
            invitation_id=row["invitation_id"],
            token=row["token"],
            ledger_id=row["ledger_id"],
            issuer_member_id=row["issuer_member_id"],
            invite_role=Role(row["invite_role"]),
            status=InvitationStatus(row["status"]),
            expires_at=_dt(row["expires_at"]),
            used_count=row["used_count"],
            max_uses=row["max_uses"],
            created_at=_dt(row["created_at"]),
        )


class CategoryRepository(BaseRepository):
    """分类仓储。"""

    def save(self, category: Category) -> None:
        """保存或更新分类。"""
        self._execute(
            """
            INSERT INTO categories (category_id, ledger_id, name, is_default,
                                   status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(category_id) DO UPDATE SET
                name = excluded.name,
                status = excluded.status
            """,
            (
                category.category_id,
                category.ledger_id,
                category.name,
                int(category.is_default),
                category.status.value,
                category.created_at.isoformat(),
            ),
        )

    def find_by_id(self, category_id: str) -> Optional[Category]:
        """按标识查找分类。"""
        row = self._one("SELECT * FROM categories WHERE category_id = ?", (category_id,))
        return self._to_category(row) if row else None

    def find_by_name(self, ledger_id: str, name: str) -> Optional[Category]:
        """按账本与名称查找分类。"""
        row = self._one(
            "SELECT * FROM categories WHERE ledger_id = ? AND name = ?",
            (ledger_id, name),
        )
        return self._to_category(row) if row else None

    def list_by_ledger(self, ledger_id: str) -> List[Category]:
        """列出账本内全部分类。"""
        rows = self._query(
            "SELECT * FROM categories WHERE ledger_id = ? "
            "ORDER BY is_default DESC, created_at ASC, rowid ASC",
            (ledger_id,),
        )
        return [self._to_category(row) for row in rows]

    def delete(self, category_id: str) -> None:
        """删除分类。"""
        self._execute("DELETE FROM categories WHERE category_id = ?", (category_id,))

    def count_usage(self, category_id: str) -> int:
        """统计引用该分类的记录条数。"""
        row = self._one(
            "SELECT COUNT(*) AS total FROM records WHERE category_id = ?",
            (category_id,),
        )
        return int(row["total"]) if row else 0

    @staticmethod
    def _to_category(row: sqlite3.Row) -> Category:
        """把结果行转换为分类实体。"""
        return Category(
            category_id=row["category_id"],
            ledger_id=row["ledger_id"],
            name=row["name"],
            is_default=bool(row["is_default"]),
            status=CategoryStatus(row["status"]),
            created_at=_dt(row["created_at"]),
        )


class RecordRepository(BaseRepository):
    """收支记录仓储。"""

    def save(self, record: Record) -> None:
        """保存或更新记录。"""
        self._execute(
            """
            INSERT INTO records (record_id, ledger_id, creator_id, payer_id,
                                 category_id, type, amount, record_date, note,
                                 status, version, request_id, reversal_of_id,
                                 reversed_by_id, created_at, submitted_at,
                                 reviewed_at, reviewer_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id) DO UPDATE SET
                payer_id = excluded.payer_id,
                category_id = excluded.category_id,
                type = excluded.type,
                amount = excluded.amount,
                record_date = excluded.record_date,
                note = excluded.note,
                status = excluded.status,
                version = excluded.version,
                request_id = excluded.request_id,
                reversal_of_id = excluded.reversal_of_id,
                reversed_by_id = excluded.reversed_by_id,
                submitted_at = excluded.submitted_at,
                reviewed_at = excluded.reviewed_at,
                reviewer_id = excluded.reviewer_id
            """,
            (
                record.record_id,
                record.ledger_id,
                record.creator_id,
                record.payer_id,
                record.category_id,
                record.type.value,
                str(record.amount),
                record.record_date.isoformat(),
                record.note,
                record.status.value,
                record.version,
                record.request_id,
                record.reversal_of_id,
                record.reversed_by_id,
                record.created_at.isoformat(),
                record.submitted_at.isoformat() if record.submitted_at else None,
                record.reviewed_at.isoformat() if record.reviewed_at else None,
                record.reviewer_id,
            ),
        )

    def find_by_id(self, record_id: str) -> Optional[Record]:
        """按标识查找记录。"""
        row = self._one(
            """
            SELECT r.*, c.name AS category_name, pu.display_name AS payer_name,
                   cu.display_name AS creator_name
            FROM records r
            LEFT JOIN categories c ON c.category_id = r.category_id
            LEFT JOIN users pu ON pu.user_id = r.payer_id
            LEFT JOIN users cu ON cu.user_id = r.creator_id
            WHERE r.record_id = ?
            """,
            (record_id,),
        )
        return self._to_record(row) if row else None

    def list_by_ledger(self, ledger_id: str) -> List[Record]:
        """列出账本内全部记录。"""
        rows = self._query(
            """
            SELECT r.*, c.name AS category_name, pu.display_name AS payer_name,
                   cu.display_name AS creator_name
            FROM records r
            LEFT JOIN categories c ON c.category_id = r.category_id
            LEFT JOIN users pu ON pu.user_id = r.payer_id
            LEFT JOIN users cu ON cu.user_id = r.creator_id
            WHERE r.ledger_id = ?
            ORDER BY r.created_at DESC
            """,
            (ledger_id,),
        )
        return [self._to_record(row) for row in rows]

    def list_by_status(self, ledger_id: str, status: RecordStatus) -> List[Record]:
        """按状态列出账本内记录。"""
        rows = self._query(
            """
            SELECT r.*, c.name AS category_name, pu.display_name AS payer_name,
                   cu.display_name AS creator_name
            FROM records r
            LEFT JOIN categories c ON c.category_id = r.category_id
            LEFT JOIN users pu ON pu.user_id = r.payer_id
            LEFT JOIN users cu ON cu.user_id = r.creator_id
            WHERE r.ledger_id = ? AND r.status = ?
            ORDER BY r.submitted_at ASC
            """,
            (ledger_id, status.value),
        )
        return [self._to_record(row) for row in rows]

    def list_approved(self, ledger_id: str) -> List[Record]:
        """列出账本内已通过的记录，统计与结算的唯一数据来源。"""
        return self.list_by_status(ledger_id, RecordStatus.APPROVED)

    def count_by_ledger(self, ledger_id: str) -> int:
        """统计账本内记录总数。"""
        row = self._one(
            "SELECT COUNT(*) AS total FROM records WHERE ledger_id = ?", (ledger_id,)
        )
        return int(row["total"]) if row else 0

    def find_by_request_id(self, request_id: str) -> Optional[Record]:
        """按请求标识查找记录。"""
        if not request_id:
            return None
        row = self._one(
            "SELECT * FROM records WHERE request_id = ? ORDER BY created_at ASC",
            (request_id,),
        )
        return self._to_record(row) if row else None

    def query(self, ledger_id: str, criteria: RecordFilter) -> Page:
        """按多条件组合分页查询记录，对应 REQ-023。

        :param ledger_id: 账本标识。
        :param criteria: 查询条件。
        :return: 分页结果。
        """
        conditions = ["r.ledger_id = ?"]
        params: List[Any] = [ledger_id]

        if criteria.record_type is not None:
            conditions.append("r.type = ?")
            params.append(criteria.record_type.value)
        if criteria.category_id:
            conditions.append("r.category_id = ?")
            params.append(criteria.category_id)
        if criteria.status is not None:
            conditions.append("r.status = ?")
            params.append(criteria.status.value)
        if criteria.date_from:
            conditions.append("r.record_date >= ?")
            params.append(criteria.date_from.isoformat())
        if criteria.date_to:
            conditions.append("r.record_date <= ?")
            params.append(criteria.date_to.isoformat())
        if criteria.amount_min is not None:
            conditions.append("CAST(r.amount AS REAL) >= ?")
            params.append(float(criteria.amount_min))
        if criteria.amount_max is not None:
            conditions.append("CAST(r.amount AS REAL) <= ?")
            params.append(float(criteria.amount_max))
        if criteria.member_id:
            conditions.append(
                "(r.payer_id = ? OR r.creator_id = ? OR EXISTS ("
                "SELECT 1 FROM share_items s WHERE s.record_id = r.record_id "
                "AND s.member_id = ?))"
            )
            params.extend([criteria.member_id] * 3)
        if criteria.keyword:
            conditions.append("(r.note LIKE ? OR r.amount LIKE ?)")
            params.extend([f"%{criteria.keyword}%", f"%{criteria.keyword}%"])

        where = " AND ".join(conditions)
        total_row = self._one(
            f"SELECT COUNT(*) AS total FROM records r WHERE {where}", params
        )
        total = int(total_row["total"]) if total_row else 0

        offset = (criteria.page - 1) * criteria.page_size
        rows = self._query(
            f"""
            SELECT r.*, c.name AS category_name, pu.display_name AS payer_name,
                   cu.display_name AS creator_name
            FROM records r
            LEFT JOIN categories c ON c.category_id = r.category_id
            LEFT JOIN users pu ON pu.user_id = r.payer_id
            LEFT JOIN users cu ON cu.user_id = r.creator_id
            WHERE {where}
            ORDER BY r.created_at DESC
            LIMIT ? OFFSET ?
            """,
            list(params) + [criteria.page_size, offset],
        )
        items = [self._to_record(row) for row in rows]
        return Page(
            items=items,
            total=total,
            page=criteria.page,
            page_size=criteria.page_size,
        )

    def statistics_rows(self, ledger_id: str) -> List[sqlite3.Row]:
        """返回参与统计的记录明细行，只含已通过记录。

        统计口径集中在仓储层实现一次（REQ-024、REQ-043）。

        :param ledger_id: 账本标识。
        :return: 记录明细行。
        """
        return self._query(
            """
            SELECT r.record_id, r.type, r.amount, r.record_date, r.category_id,
                   r.payer_id, r.creator_id
            FROM records r
            WHERE r.ledger_id = ? AND r.status = ?
            """,
            (ledger_id, RecordStatus.APPROVED.value),
        )

    @staticmethod
    def _to_record(row: sqlite3.Row) -> Record:
        """把结果行转换为记录实体。"""
        keys = row.keys()
        return Record(
            record_id=row["record_id"],
            ledger_id=row["ledger_id"],
            creator_id=row["creator_id"],
            payer_id=row["payer_id"],
            category_id=row["category_id"],
            type=RecordType(row["type"]),
            amount=_dec(row["amount"]),
            record_date=date.fromisoformat(row["record_date"]),
            note=row["note"],
            status=RecordStatus(row["status"]),
            version=row["version"],
            request_id=row["request_id"],
            reversal_of_id=row["reversal_of_id"],
            reversed_by_id=row["reversed_by_id"],
            created_at=_dt(row["created_at"]),
            submitted_at=_dt(row["submitted_at"]),
            reviewed_at=_dt(row["reviewed_at"]),
            reviewer_id=row["reviewer_id"],
            category_name=row["category_name"] if "category_name" in keys else "",
            payer_name=row["payer_name"] if "payer_name" in keys else "",
            creator_name=row["creator_name"] if "creator_name" in keys else "",
        )


class ShareItemRepository(BaseRepository):
    """分摊明细仓储。"""

    def save_many(self, items: Sequence[ShareItem]) -> None:
        """批量保存分摊明细。"""
        for item in items:
            self._execute(
                """
                INSERT INTO share_items (share_id, record_id, member_id, amount,
                                         is_remainder_holder)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(share_id) DO UPDATE SET
                    member_id = excluded.member_id,
                    amount = excluded.amount,
                    is_remainder_holder = excluded.is_remainder_holder
                """,
                (
                    item.share_id,
                    item.record_id,
                    item.member_id,
                    str(item.amount),
                    int(item.is_remainder_holder),
                ),
            )

    def replace_for_record(self, record_id: str, items: Sequence[ShareItem]) -> None:
        """整体替换某条记录的分摊明细。

        :param record_id: 记录标识。
        :param items: 新的分摊明细。
        """
        self._execute("DELETE FROM share_items WHERE record_id = ?", (record_id,))
        self.save_many(items)

    def list_by_record(self, record_id: str) -> List[ShareItem]:
        """列出某条记录的全部分摊明细。"""
        rows = self._query(
            """
            SELECT s.*, u.display_name AS member_name
            FROM share_items s
            LEFT JOIN ledger_members lm ON lm.member_id = s.member_id
            LEFT JOIN users u ON u.user_id = lm.user_id
            WHERE s.record_id = ?
            ORDER BY s.is_remainder_holder DESC, s.amount DESC
            """,
            (record_id,),
        )
        return [
            ShareItem(
                share_id=row["share_id"],
                record_id=row["record_id"],
                member_id=row["member_id"],
                amount=_dec(row["amount"]),
                is_remainder_holder=bool(row["is_remainder_holder"]),
                member_name=row["member_name"] if "member_name" in row.keys() else "",
            )
            for row in rows
        ]

    def list_by_ledger(self, ledger_id: str) -> List[ShareItem]:
        """列出账本内全部分摊明细，供成员统计使用。"""
        rows = self._query(
            """
            SELECT s.*, u.display_name AS member_name
            FROM share_items s
            JOIN records r ON r.record_id = s.record_id
            LEFT JOIN ledger_members lm ON lm.member_id = s.member_id
            LEFT JOIN users u ON u.user_id = lm.user_id
            WHERE r.ledger_id = ?
            """,
            (ledger_id,),
        )
        return [
            ShareItem(
                share_id=row["share_id"],
                record_id=row["record_id"],
                member_id=row["member_id"],
                amount=_dec(row["amount"]),
                is_remainder_holder=bool(row["is_remainder_holder"]),
                member_name=row["member_name"] if "member_name" in row.keys() else "",
            )
            for row in rows
        ]


class RecordTraceRepository(BaseRepository):
    """记录历史仓储。"""

    def save(self, trace: RecordTrace) -> None:
        """保存一条记录历史。"""
        self._execute(
            """
            INSERT INTO record_traces (trace_id, record_id, action, actor_id, reason,
                                       from_status, to_status, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace.trace_id,
                trace.record_id,
                trace.action.value,
                trace.actor_id,
                trace.reason,
                trace.from_status.value if trace.from_status else None,
                trace.to_status.value if trace.to_status else None,
                trace.occurred_at.isoformat(),
            ),
        )

    def list_by_record(self, record_id: str) -> List[RecordTrace]:
        """列出某条记录的全部历史。"""
        rows = self._query(
            """
            SELECT t.*, u.display_name AS actor_name
            FROM record_traces t
            LEFT JOIN ledger_members lm ON lm.member_id = t.actor_id
            LEFT JOIN users u ON u.user_id = lm.user_id
            WHERE t.record_id = ?
            ORDER BY t.occurred_at ASC
            """,
            (record_id,),
        )
        return [
            RecordTrace(
                trace_id=row["trace_id"],
                record_id=row["record_id"],
                action=LogActionType(row["action"]),
                actor_id=row["actor_id"],
                reason=row["reason"],
                from_status=(
                    RecordStatus(row["from_status"]) if row["from_status"] else None
                ),
                to_status=RecordStatus(row["to_status"]) if row["to_status"] else None,
                occurred_at=_dt(row["occurred_at"]),
                actor_name=row["actor_name"] if "actor_name" in row.keys() else "",
            )
            for row in rows
        ]


class BudgetRepository(BaseRepository):
    """预算仓储。"""

    def save(self, budget: Budget) -> None:
        """保存或更新预算。"""
        self._execute(
            """
            INSERT INTO budgets (budget_id, ledger_id, category_id, amount,
                                 warning_ratio, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(budget_id) DO UPDATE SET
                amount = excluded.amount,
                warning_ratio = excluded.warning_ratio
            """,
            (
                budget.budget_id,
                budget.ledger_id,
                budget.category_id,
                str(budget.amount),
                str(budget.warning_ratio),
                budget.created_by,
                budget.created_at.isoformat(),
            ),
        )

    def find_by_id(self, budget_id: str) -> Optional[Budget]:
        """按标识查找预算。"""
        row = self._one("SELECT * FROM budgets WHERE budget_id = ?", (budget_id,))
        return self._to_budget(row) if row else None

    def find(self, ledger_id: str, category_id: Optional[str]) -> Optional[Budget]:
        """按账本与分类查找预算，分类为空表示账本总预算。"""
        if category_id:
            row = self._one(
                "SELECT * FROM budgets WHERE ledger_id = ? AND category_id = ?",
                (ledger_id, category_id),
            )
        else:
            row = self._one(
                "SELECT * FROM budgets WHERE ledger_id = ? AND category_id IS NULL",
                (ledger_id,),
            )
        return self._to_budget(row) if row else None

    def list_by_ledger(self, ledger_id: str) -> List[Budget]:
        """列出账本内全部预算。"""
        rows = self._query(
            """
            SELECT b.*, c.name AS category_name
            FROM budgets b
            LEFT JOIN categories c ON c.category_id = b.category_id
            WHERE b.ledger_id = ?
            ORDER BY b.category_id IS NOT NULL ASC, c.name ASC
            """,
            (ledger_id,),
        )
        return [self._to_budget(row) for row in rows]

    @staticmethod
    def _to_budget(row: sqlite3.Row) -> Budget:
        """把结果行转换为预算实体。"""
        keys = row.keys()
        return Budget(
            budget_id=row["budget_id"],
            ledger_id=row["ledger_id"],
            category_id=row["category_id"],
            amount=_dec(row["amount"]),
            warning_ratio=_dec(row["warning_ratio"]),
            created_by=row["created_by"],
            created_at=_dt(row["created_at"]),
            category_name=row["category_name"] if "category_name" in keys else "",
        )


class SettlementRepository(BaseRepository):
    """结算单仓储。"""

    def save(self, settlement: Settlement) -> None:
        """保存或更新结算单。"""
        self._execute(
            """
            INSERT INTO settlements (settlement_id, ledger_id, status, created_by,
                                     created_at, confirmed_at, verdict,
                                     verdict_reason, snapshot_record_ids)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(settlement_id) DO UPDATE SET
                status = excluded.status,
                confirmed_at = excluded.confirmed_at,
                verdict = excluded.verdict,
                verdict_reason = excluded.verdict_reason
            """,
            (
                settlement.settlement_id,
                settlement.ledger_id,
                settlement.status.value,
                settlement.created_by,
                settlement.created_at.isoformat(),
                settlement.confirmed_at.isoformat() if settlement.confirmed_at else None,
                settlement.verdict,
                settlement.verdict_reason,
                json.dumps(settlement.snapshot_record_ids, ensure_ascii=False),
            ),
        )

    def find_by_id(self, settlement_id: str) -> Optional[Settlement]:
        """按标识查找结算单。"""
        row = self._one(
            "SELECT * FROM settlements WHERE settlement_id = ?", (settlement_id,)
        )
        return self._to_settlement(row) if row else None

    def list_by_ledger(self, ledger_id: str) -> List[Settlement]:
        """列出账本内全部结算单，按创建时间倒序。"""
        rows = self._query(
            "SELECT * FROM settlements WHERE ledger_id = ? ORDER BY created_at DESC",
            (ledger_id,),
        )
        return [self._to_settlement(row) for row in rows]

    @staticmethod
    def _to_settlement(row: sqlite3.Row) -> Settlement:
        """把结果行转换为结算单实体。"""
        try:
            snapshot = json.loads(row["snapshot_record_ids"])
        except (TypeError, ValueError):
            snapshot = []
        return Settlement(
            settlement_id=row["settlement_id"],
            ledger_id=row["ledger_id"],
            status=SettlementStatus(row["status"]),
            created_by=row["created_by"],
            created_at=_dt(row["created_at"]),
            confirmed_at=_dt(row["confirmed_at"]),
            verdict=row["verdict"],
            verdict_reason=row["verdict_reason"],
            snapshot_record_ids=list(snapshot),
        )


class SettlementMemberRepository(BaseRepository):
    """结算成员仓储。"""

    def save(self, item: SettlementMember) -> None:
        """保存或更新结算成员快照。"""
        self._execute(
            """
            INSERT INTO settlement_members (settlement_id, member_id, net_amount,
                                           confirmed, confirmed_at, appealed,
                                           appeal_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(settlement_id, member_id) DO UPDATE SET
                net_amount = excluded.net_amount,
                confirmed = excluded.confirmed,
                confirmed_at = excluded.confirmed_at,
                appealed = excluded.appealed,
                appeal_reason = excluded.appeal_reason
            """,
            (
                item.settlement_id,
                item.member_id,
                str(item.net_amount),
                int(item.confirmed),
                item.confirmed_at.isoformat() if item.confirmed_at else None,
                int(item.appealed),
                item.appeal_reason,
            ),
        )

    def list_by_settlement(self, settlement_id: str) -> List[SettlementMember]:
        """列出结算单内的全部成员快照。"""
        rows = self._query(
            """
            SELECT s.*, u.display_name AS member_name
            FROM settlement_members s
            LEFT JOIN ledger_members lm ON lm.member_id = s.member_id
            LEFT JOIN users u ON u.user_id = lm.user_id
            WHERE s.settlement_id = ?
            ORDER BY s.net_amount DESC
            """,
            (settlement_id,),
        )
        return [
            SettlementMember(
                member_id=row["member_id"],
                settlement_id=row["settlement_id"],
                net_amount=_dec(row["net_amount"]),
                confirmed=bool(row["confirmed"]),
                confirmed_at=_dt(row["confirmed_at"]),
                appealed=bool(row["appealed"]),
                appeal_reason=row["appeal_reason"],
                member_name=row["member_name"] if "member_name" in row.keys() else "",
            )
            for row in rows
        ]

    def find(self, settlement_id: str, member_id: str) -> Optional[SettlementMember]:
        """查找结算单内某位成员的快照。"""
        row = self._one(
            "SELECT * FROM settlement_members WHERE settlement_id = ? AND member_id = ?",
            (settlement_id, member_id),
        )
        if not row:
            return None
        return SettlementMember(
            member_id=row["member_id"],
            settlement_id=row["settlement_id"],
            net_amount=_dec(row["net_amount"]),
            confirmed=bool(row["confirmed"]),
            confirmed_at=_dt(row["confirmed_at"]),
            appealed=bool(row["appealed"]),
            appeal_reason=row["appeal_reason"],
        )


class TransferPlanRepository(BaseRepository):
    """转账方案仓储。"""

    def save_many(self, items: Sequence[TransferPlanItem]) -> None:
        """批量保存转账方案条目。"""
        for item in items:
            self._execute(
                """
                INSERT INTO transfer_plan_items (item_id, settlement_id, seq,
                                                 from_member_id, to_member_id, amount)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    seq = excluded.seq,
                    from_member_id = excluded.from_member_id,
                    to_member_id = excluded.to_member_id,
                    amount = excluded.amount
                """,
                (
                    item.item_id,
                    item.settlement_id,
                    item.seq,
                    item.from_member_id,
                    item.to_member_id,
                    str(item.amount),
                ),
            )

    def list_by_settlement(self, settlement_id: str) -> List[TransferPlanItem]:
        """列出结算单的全部转账条目。"""
        rows = self._query(
            """
            SELECT t.*, fu.display_name AS from_name, tu.display_name AS to_name
            FROM transfer_plan_items t
            LEFT JOIN ledger_members flm ON flm.member_id = t.from_member_id
            LEFT JOIN ledger_members tlm ON tlm.member_id = t.to_member_id
            LEFT JOIN users fu ON fu.user_id = flm.user_id
            LEFT JOIN users tu ON tu.user_id = tlm.user_id
            WHERE t.settlement_id = ?
            ORDER BY t.seq ASC
            """,
            (settlement_id,),
        )
        return [
            TransferPlanItem(
                item_id=row["item_id"],
                settlement_id=row["settlement_id"],
                seq=row["seq"],
                from_member_id=row["from_member_id"],
                to_member_id=row["to_member_id"],
                amount=_dec(row["amount"]),
                from_member_name=row["from_name"] if "from_name" in row.keys() else "",
                to_member_name=row["to_name"] if "to_name" in row.keys() else "",
            )
            for row in rows
        ]


class OperationLogRepository(BaseRepository):
    """操作日志仓储。

    本仓储只提供追加与查询，不提供更新与删除方法，
    以在接口层面保证「日志只增不改不删」（REQ-040）。
    """

    def save(self, log: OperationLog) -> None:
        """追加一条操作日志。"""
        self._execute(
            """
            INSERT INTO operation_logs (log_id, ledger_id, actor_id, action,
                                        target_type, target_id, params, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log.log_id,
                log.ledger_id,
                log.actor_id,
                log.action.value,
                log.target_type,
                log.target_id,
                log.params,
                log.occurred_at.isoformat(),
            ),
        )

    def list_by_ledger(self, ledger_id: str) -> List[OperationLog]:
        """列出账本内全部日志，按时间倒序。"""
        rows = self._query(
            """
            SELECT l.*, u.display_name AS actor_name
            FROM operation_logs l
            LEFT JOIN ledger_members lm ON lm.member_id = l.actor_id
            LEFT JOIN users u ON u.user_id = lm.user_id
            WHERE l.ledger_id = ?
            ORDER BY l.occurred_at DESC
            """,
            (ledger_id,),
        )
        return [self._to_log(row) for row in rows]

    def list_by_actor(self, ledger_id: str, actor_id: str) -> List[OperationLog]:
        """列出与指定成员相关的日志。

        记账成员只能查询与自己相关的日志（REQ-040）。

        :param ledger_id: 账本标识。
        :param actor_id: 成员标识。
        :return: 日志列表。
        """
        rows = self._query(
            """
            SELECT l.*, u.display_name AS actor_name
            FROM operation_logs l
            LEFT JOIN ledger_members lm ON lm.member_id = l.actor_id
            LEFT JOIN users u ON u.user_id = lm.user_id
            WHERE l.ledger_id = ?
              AND (l.actor_id = ? OR l.target_id = ?)
            ORDER BY l.occurred_at DESC
            """,
            (ledger_id, actor_id, actor_id),
        )
        return [self._to_log(row) for row in rows]

    @staticmethod
    def _to_log(row: sqlite3.Row) -> OperationLog:
        """把结果行转换为日志实体。"""
        keys = row.keys()
        return OperationLog(
            log_id=row["log_id"],
            ledger_id=row["ledger_id"],
            actor_id=row["actor_id"],
            action=LogActionType(row["action"]),
            target_type=row["target_type"],
            target_id=row["target_id"],
            params=row["params"],
            occurred_at=_dt(row["occurred_at"]),
            actor_name=row["actor_name"] if "actor_name" in keys else "",
        )


class RequestDedupRepository(BaseRepository):
    """请求去重仓储，同时实现支撑层 ``DedupStore`` 协议。"""

    def find_active(self, request_id: str, now: datetime) -> Optional[RequestDedup]:
        """查找仍在保留期内的幂等记录。

        :param request_id: 请求标识。
        :param now: 当前时间。
        :return: 幂等记录，不存在或已过期时返回 ``None``。
        """
        row = self._one(
            "SELECT * FROM request_dedups WHERE request_id = ? AND expire_at > ?",
            (request_id, now.isoformat()),
        )
        if not row:
            return None
        return RequestDedup(
            request_id=row["request_id"],
            user_id=row["user_id"],
            result_record_id=row["result_record_id"],
            created_at=_dt(row["created_at"]),
            expire_at=_dt(row["expire_at"]),
        )

    def save(self, dedup_record: RequestDedup) -> None:
        """保存一条幂等记录。"""
        self._execute(
            """
            INSERT INTO request_dedups (request_id, user_id, result_record_id,
                                        created_at, expire_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(request_id) DO UPDATE SET
                result_record_id = excluded.result_record_id,
                expire_at = excluded.expire_at
            """,
            (
                dedup_record.request_id,
                dedup_record.user_id,
                dedup_record.result_record_id,
                dedup_record.created_at.isoformat(),
                dedup_record.expire_at.isoformat(),
            ),
        )

    def purge_expired(self, now: datetime) -> int:
        """删除已过期的幂等记录。

        :param now: 当前时间。
        :return: 删除条数。
        """
        cursor = self.connection.execute(
            "DELETE FROM request_dedups WHERE expire_at <= ?", (now.isoformat(),)
        )
        if not self._db.in_transaction:
            self.connection.commit()
        return cursor.rowcount


class RepositoryRegistry:
    """仓储集合。

    把各仓储聚合到一个对象里，业务服务只依赖这一个入口，
    便于在单元测试中整体替换。
    """

    def __init__(self, database: Any) -> None:
        """初始化全部仓储。

        :param database: 数据库封装。
        """
        self.database = database
        self.users = UserRepository(database)
        self.ledgers = LedgerRepository(database)
        self.members = LedgerMemberRepository(database)
        self.invitations = InvitationRepository(database)
        self.categories = CategoryRepository(database)
        self.records = RecordRepository(database)
        self.shares = ShareItemRepository(database)
        self.traces = RecordTraceRepository(database)
        self.budgets = BudgetRepository(database)
        self.settlements = SettlementRepository(database)
        self.settlement_members = SettlementMemberRepository(database)
        self.transfer_plans = TransferPlanRepository(database)
        self.logs = OperationLogRepository(database)
        self.dedups = RequestDedupRepository(database)

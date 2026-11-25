"""数据访问基础设施。

对应实验二组件图中的数据层。

本模块负责三件事：建立 SQLite 连接、按实验一数据模型建表、封装事务。
业务代码不直接写 SQL，统一通过仓储类访问，这样统计口径与查询性能
都能在仓储层集中处理。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id      TEXT PRIMARY KEY,
        account_name TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'ACTIVE',
        password_hash TEXT NOT NULL DEFAULT '',
        created_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ledgers (
        ledger_id       TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        admin_member_id TEXT NOT NULL DEFAULT '',
        created_at      TEXT NOT NULL,
        member_limit    INTEGER NOT NULL DEFAULT 50,
        record_limit    INTEGER NOT NULL DEFAULT 100000
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_members (
        member_id           TEXT PRIMARY KEY,
        user_id             TEXT NOT NULL,
        ledger_id           TEXT NOT NULL,
        role                TEXT NOT NULL,
        status              TEXT NOT NULL,
        joined_at           TEXT NOT NULL,
        settlement_eligible INTEGER NOT NULL DEFAULT 0,
        UNIQUE (ledger_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS invitations (
        invitation_id   TEXT PRIMARY KEY,
        token           TEXT NOT NULL UNIQUE,
        ledger_id       TEXT NOT NULL,
        issuer_member_id TEXT NOT NULL,
        invite_role     TEXT NOT NULL,
        status          TEXT NOT NULL,
        expires_at      TEXT NOT NULL,
        used_count      INTEGER NOT NULL DEFAULT 0,
        max_uses        INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS categories (
        category_id TEXT PRIMARY KEY,
        ledger_id   TEXT NOT NULL,
        name        TEXT NOT NULL,
        is_default  INTEGER NOT NULL DEFAULT 0,
        status      TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        UNIQUE (ledger_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS records (
        record_id      TEXT PRIMARY KEY,
        ledger_id      TEXT NOT NULL,
        creator_id     TEXT NOT NULL,
        payer_id       TEXT NOT NULL,
        category_id    TEXT NOT NULL,
        type           TEXT NOT NULL,
        amount         TEXT NOT NULL,
        record_date    TEXT NOT NULL,
        note           TEXT NOT NULL DEFAULT '',
        status         TEXT NOT NULL,
        version        INTEGER NOT NULL DEFAULT 1,
        request_id     TEXT NOT NULL DEFAULT '',
        reversal_of_id TEXT,
        reversed_by_id TEXT,
        created_at     TEXT NOT NULL,
        submitted_at   TEXT,
        reviewed_at    TEXT,
        reviewer_id    TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS share_items (
        share_id            TEXT PRIMARY KEY,
        record_id           TEXT NOT NULL,
        member_id           TEXT NOT NULL,
        amount              TEXT NOT NULL,
        is_remainder_holder INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS record_traces (
        trace_id    TEXT PRIMARY KEY,
        record_id   TEXT NOT NULL,
        action      TEXT NOT NULL,
        actor_id    TEXT NOT NULL,
        reason      TEXT NOT NULL DEFAULT '',
        from_status TEXT,
        to_status   TEXT,
        occurred_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS budgets (
        budget_id    TEXT PRIMARY KEY,
        ledger_id    TEXT NOT NULL,
        category_id  TEXT,
        amount       TEXT NOT NULL,
        warning_ratio TEXT NOT NULL DEFAULT '0.9',
        created_by   TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        UNIQUE (ledger_id, category_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settlements (
        settlement_id      TEXT PRIMARY KEY,
        ledger_id          TEXT NOT NULL,
        status             TEXT NOT NULL,
        created_by         TEXT NOT NULL,
        created_at         TEXT NOT NULL,
        confirmed_at       TEXT,
        verdict            TEXT NOT NULL DEFAULT '',
        verdict_reason     TEXT NOT NULL DEFAULT '',
        snapshot_record_ids TEXT NOT NULL DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settlement_members (
        settlement_id TEXT NOT NULL,
        member_id     TEXT NOT NULL,
        net_amount    TEXT NOT NULL,
        confirmed     INTEGER NOT NULL DEFAULT 0,
        confirmed_at  TEXT,
        appealed      INTEGER NOT NULL DEFAULT 0,
        appeal_reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (settlement_id, member_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transfer_plan_items (
        item_id        TEXT PRIMARY KEY,
        settlement_id  TEXT NOT NULL,
        seq            INTEGER NOT NULL,
        from_member_id TEXT NOT NULL,
        to_member_id   TEXT NOT NULL,
        amount         TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS operation_logs (
        log_id      TEXT PRIMARY KEY,
        ledger_id   TEXT NOT NULL,
        actor_id    TEXT NOT NULL,
        action      TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id   TEXT NOT NULL,
        params      TEXT NOT NULL DEFAULT '',
        occurred_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS request_dedups (
        request_id       TEXT PRIMARY KEY,
        user_id          TEXT NOT NULL,
        result_record_id TEXT NOT NULL DEFAULT '',
        created_at       TEXT NOT NULL,
        expire_at        TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_members_ledger ON ledger_members (ledger_id)",
    "CREATE INDEX IF NOT EXISTS idx_records_ledger ON records (ledger_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_records_date ON records (ledger_id, record_date)",
    "CREATE INDEX IF NOT EXISTS idx_shares_record ON share_items (record_id)",
    "CREATE INDEX IF NOT EXISTS idx_traces_record ON record_traces (record_id)",
    "CREATE INDEX IF NOT EXISTS idx_logs_ledger ON operation_logs (ledger_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_settle_ledger ON settlements (ledger_id, created_at)",
)


class Database:
    """SQLite 数据库封装。

    对外暴露一个连接工厂与一个事务上下文，保证「日志写入失败则关键操作
    整体回滚」这一事务语义（REQ-039）能被自然地表达出来。
    """

    def __init__(self, path: str = ":memory:") -> None:
        """初始化数据库。

        :param path: 数据库文件路径，``:memory:`` 表示内存数据库，
            单元测试使用内存库以保证彼此隔离。
        """
        self._path = path
        self._connection: Optional[sqlite3.Connection] = None
        self._transaction_depth = 0
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)

    @property
    def in_transaction(self) -> bool:
        """判断当前是否处于显式事务中。

        仓储据此决定是否立即提交：在显式事务内不提交，
        以保证「关键操作与其日志同生共死」（REQ-039）。
        """
        return self._transaction_depth > 0

    @property
    def path(self) -> str:
        """返回数据库文件路径。"""
        return self._path

    @property
    def connection(self) -> sqlite3.Connection:
        """返回当前连接，首次调用时创建。"""
        if self._connection is None:
            self._connection = sqlite3.connect(self._path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    def initialize(self) -> None:
        """建立全部数据表与索引。"""
        cursor = self.connection.cursor()
        try:
            for statement in SCHEMA_STATEMENTS:
                cursor.execute(statement)
            self.connection.commit()
        finally:
            cursor.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """开启一个事务，块内抛异常时整体回滚。

        事务支持嵌套，内层复用外层事务，只有最外层负责提交或回滚。

        :return: 事务上下文，产出当前连接。
        """
        connection = self.connection
        outermost = self._transaction_depth == 0
        if outermost:
            connection.execute("BEGIN")
        self._transaction_depth += 1
        try:
            yield connection
        except Exception:
            self._transaction_depth -= 1
            if outermost:
                connection.rollback()
            raise
        self._transaction_depth -= 1
        if outermost:
            connection.commit()

    def commit(self) -> None:
        """提交当前事务。

        :raises sqlite3.Error: 提交失败时抛出原始异常。
        """
        self.connection.commit()

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

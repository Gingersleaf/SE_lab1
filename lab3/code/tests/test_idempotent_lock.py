"""幂等去重与乐观锁的单元测试（支撑层）。

对应支撑模块组件 ``IdempotentGuard`` 与 ``OptimisticLock``，
覆盖 REQ-035（重复提交的幂等去重）与 REQ-037（并发编辑的版本号校验）。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from shared_ledger.domain.entities import RequestDedup
from shared_ledger.domain.errors import VersionConflictError
from shared_ledger.support.idempotent_guard import IdempotentGuard
from shared_ledger.support.optimistic_lock import OptimisticLock

from tests.base import ContextTestCase, LedgerTestCase


class MemoryDedupStore:
    """内存版幂等记录存储，用于单独验证 ``IdempotentGuard`` 的组件行为。"""

    def __init__(self) -> None:
        """初始化空的存储。"""
        self.records: List[RequestDedup] = []

    def find_active(self, request_id: str, now: datetime) -> Optional[RequestDedup]:
        """返回仍在保留期内的幂等记录。"""
        for item in self.records:
            if item.request_id == request_id and item.expire_at > now:
                return item
        return None

    def save(self, dedup_record: RequestDedup) -> None:
        """保存或覆盖一条幂等记录。"""
        for index, item in enumerate(self.records):
            if item.request_id == dedup_record.request_id:
                self.records[index] = dedup_record
                return
        self.records.append(dedup_record)

    def purge_expired(self, now: datetime) -> int:
        """删除已过期的幂等记录，返回删除条数。"""
        before = len(self.records)
        self.records = [item for item in self.records if item.expire_at > now]
        return before - len(self.records)


class IdempotentGuardComponentTest(ContextTestCase):
    """``IdempotentGuard`` 组件的独立用例。"""

    def setUp(self) -> None:
        """在内存上下文之上建立一个内存幂等存储。"""
        super().setUp()
        self.store = MemoryDedupStore()
        self.guard = IdempotentGuard(self.store)
        self.now = datetime(2026, 11, 10, 12, 0, 0)

    def test_保留期为七天(self) -> None:
        """验证 REQ-035：幂等标识在服务端的保留期为七天。"""
        self.assertEqual(IdempotentGuard.RETENTION_DAYS, 7)
        self.assertEqual(self.guard.retention, timedelta(days=7))

    def test_保留期内重复标识返回首次结果(self) -> None:
        """验证 REQ-035：保留期内同一标识查到首次产生的记录标识。"""
        self.guard.remember("REQ-1", "U1", "R-1", self.now)
        self.assertEqual(self.guard.lookup("REQ-1", self.now), "R-1")
        self.assertEqual(
            self.guard.lookup("REQ-1", self.now + timedelta(days=6, hours=23)), "R-1"
        )

    def test_超过保留期后同标识视为新请求(self) -> None:
        """验证 REQ-035：超过七天后同一标识不再命中首次结果。"""
        self.guard.remember("REQ-1", "U1", "R-1", self.now)
        self.assertIsNone(
            self.guard.lookup("REQ-1", self.now + timedelta(days=7, seconds=1))
        )

    def test_空标识不参与去重(self) -> None:
        """验证 REQ-035：空请求标识既不登记也不查重。"""
        self.guard.remember("", "U1", "R-1", self.now)
        self.assertIsNone(self.guard.lookup("", self.now))
        self.assertEqual(len(self.store.records), 0)

    def test_清理过期记录(self) -> None:
        """验证 REQ-035：过期记录可被清理，且清理条数正确。"""
        self.guard.remember("REQ-1", "U1", "R-1", self.now)
        self.guard.remember("REQ-2", "U1", "R-2", self.now)
        removed = self.guard.purge_expired(self.now + timedelta(days=8))
        self.assertEqual(removed, 2)
        self.assertEqual(len(self.store.records), 0)


class OptimisticLockComponentTest(ContextTestCase):
    """``OptimisticLock`` 组件的独立用例。"""

    def test_版本号一致时校验通过(self) -> None:
        """验证 REQ-037：客户端持有的版本号与服务端一致时允许保存。"""
        OptimisticLock.assert_version(3, 3)

    def test_版本号不一致时抛版本冲突异常(self) -> None:
        """验证 REQ-037：版本号不一致时拒绝保存并提示记录已被他人修改。"""
        with self.assertRaises(VersionConflictError) as ctx:
            OptimisticLock.assert_version(2, 3)
        self.assertIn("已被他人修改", str(ctx.exception))

    def test_未携带版本号时跳过校验(self) -> None:
        """验证 REQ-037：未携带版本号时不触发版本冲突。"""
        OptimisticLock.assert_version(None, 3)

    def test_下一个版本号递增一(self) -> None:
        """验证 REQ-037：保存成功后版本号递增一。"""
        self.assertEqual(OptimisticLock.next_version(1), 2)
        self.assertEqual(OptimisticLock.next_version(7), 8)


class IdempotentIntegrationTest(LedgerTestCase):
    """幂等去重与版本号校验在真实服务链路上的用例。"""

    def test_重复提交同一请求标识返回首次记录且记录总数不增加(self) -> None:
        """验证 REQ-035：同一请求标识重复提交返回首次记录，记录总数不增加。"""
        payload = self.draft_input("100.00")
        first = self.create_draft(self.writer, payload, request_id="REQ-2026-1110-0001")
        second = self.create_draft(self.writer, payload, request_id="REQ-2026-1110-0001")
        self.assertEqual(first.record_id, second.record_id)
        self.assertEqual(
            self.ctx.repos.records.count_by_ledger(self.ledger_id), 1
        )

    def test_超过保留期后同标识视为新请求(self) -> None:
        """验证 REQ-035：间隔超过七天后同标识再次提交创建新记录。"""
        payload = self.draft_input("100.00")
        first = self.create_draft(self.writer, payload, request_id="REQ-2026-1110-0002")
        self.ctx.database.connection.execute(
            "UPDATE request_dedups SET expire_at = ? WHERE request_id = ?",
            ((datetime.now() - timedelta(days=1)).isoformat(), "REQ-2026-1110-0002"),
        )
        self.ctx.database.connection.commit()
        second = self.create_draft(self.writer, payload, request_id="REQ-2026-1110-0002")
        self.assertNotEqual(first.record_id, second.record_id)
        self.assertEqual(self.ctx.repos.records.count_by_ledger(self.ledger_id), 2)

    def test_版本号不一致时保存被拒绝且原记录不变(self) -> None:
        """验证 REQ-037：使用过期版本号保存被拒绝，记录内容保持不变。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        changed = self.draft_input("150.00")
        with self.assertRaises(VersionConflictError):
            self.ctx.records.update_draft(
                self.writer.user_id,
                self.ledger_id,
                record.record_id,
                changed,
                expected_version=99,
            )
        stored = self.ctx.repos.records.find_by_id(record.record_id)
        self.assertEqual(stored.amount, Decimal("100.00"))
        self.assertEqual(stored.version, 1)

    def test_版本号一致时保存成功且版本递增(self) -> None:
        """验证 REQ-037：版本号一致时保存成功，记录版本号递增一。"""
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        updated = self.ctx.records.update_draft(
            self.writer.user_id,
            self.ledger_id,
            record.record_id,
            self.draft_input("150.00"),
            expected_version=record.version,
        )
        self.assertEqual(updated.amount, Decimal("150.00"))
        self.assertEqual(updated.version, 2)

    def test_提交动作重复触发时按幂等规则返回首次结果(self) -> None:
        """验证 REQ-008、REQ-035：提交动作被重复触发时按幂等规则处理。

        幂等查重排在状态校验与版本校验之前，因此同一个请求标识第二次
        提交时返回首次提交的结果，既不会重复产生记录，也不会被
        「当前状态不是草稿」或「版本号已变更」拦下。
        """
        record = self.create_draft(self.writer, self.draft_input("100.00"))
        first = self.submit(self.writer, record, request_id="REQ-2026-1110-0003")
        second = self.submit(self.writer, record, request_id="REQ-2026-1110-0003")
        self.assertEqual(first.record_id, second.record_id)
        self.assertEqual(
            self.ctx.repos.records.count_by_ledger(self.ledger_id), 1
        )

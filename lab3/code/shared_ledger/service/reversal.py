"""冲正生效处理。

冲正记录与原记录的关联建立与「冲正生效」是两件事：

- **建立关联**：发起冲正时生成冲正记录并互相登记标识，由记录服务负责；
- **冲正生效**：冲正记录被审核通过（或因管理员自审豁免直接通过）时，
  原记录才由已通过变为已冲正。

第二条路径有两条入口——管理员审核通过、和管理员本人提交触发自审豁免，
两条入口都必须执行同一段逻辑，否则会出现「冲正记录已通过但原记录仍是
已通过」的不一致状态。因此把它抽成本模块的独立函数由两处共同调用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..domain.entities import Record, RecordTrace
from ..domain.enums import LogActionType, RecordStatus
from ..domain.support_ids import new_uuid
from ..support.optimistic_lock import OptimisticLock
from ..support.state_guard import StateGuard


def apply_reversal_effect(
    repos: Any, reversal: Record, actor_member_id: str
) -> Optional[Record]:
    """在冲正记录生效时把原记录置为已冲正。

    :param repos: 仓储集合。
    :param reversal: 已通过的冲正记录。
    :param actor_member_id: 操作人标识。
    :return: 被更新的原记录；该记录不是冲正记录时返回 ``None``。
    """
    if not reversal.reversal_of_id:
        return None
    original = repos.records.find_by_id(reversal.reversal_of_id)
    if original is None or original.status is not RecordStatus.APPROVED:
        return None

    StateGuard.assert_record_transition(
        original.status, RecordStatus.REVERSED, subject="记录"
    )
    previous = original.status
    original.status = RecordStatus.REVERSED
    original.reversed_by_id = reversal.record_id
    original.version = OptimisticLock.next_version(original.version)
    repos.records.save(original)
    repos.traces.save(
        RecordTrace(
            trace_id=new_uuid(),
            record_id=original.record_id,
            action=LogActionType.RECORD_REVERSE,
            actor_id=actor_member_id,
            reason=f"冲正记录 {reversal.record_id} 已通过审核",
            from_status=previous,
            to_status=RecordStatus.REVERSED,
            occurred_at=datetime.now(),
        )
    )
    return original

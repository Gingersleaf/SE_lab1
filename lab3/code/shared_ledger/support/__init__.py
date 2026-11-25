"""支撑层：跨模块复用的横切规则。"""

from .amount_allocator import AmountAllocator, Participant, ShareAllocation
from .idempotent_guard import DedupStore, IdempotentGuard
from .optimistic_lock import OptimisticLock
from .state_guard import StateGuard

__all__ = [
    "AmountAllocator",
    "DedupStore",
    "IdempotentGuard",
    "OptimisticLock",
    "Participant",
    "ShareAllocation",
    "StateGuard",
]

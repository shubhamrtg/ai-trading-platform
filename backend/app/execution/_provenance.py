import threading
from typing import Any

# Bounded identity registry to prevent memory leaks while keeping exact-object provenance.
# A weak-reference implementation (like weakref.WeakSet) is unsuitable because Pydantic models
# without frozen=True are unhashable and therefore cannot be inserted into a WeakSet.
# We instead use a strictly bounded LRU-style queue of object identities.
_lock = threading.Lock()
_approved_decision_ids: set[int] = set()
_history: list[int] = []
MAX_HISTORY = 10000

def _register_approved_decision(decision: Any) -> None:
    """Internal registration of a genuine RiskEngine approved decision by exact object identity."""
    with _lock:
        did = id(decision)
        if did not in _approved_decision_ids:
            _approved_decision_ids.add(did)
            _history.append(did)
            if len(_history) > MAX_HISTORY:
                old_did = _history.pop(0)
                _approved_decision_ids.discard(old_did)

def _verify_exact_decision_provenance(decision: Any) -> bool:
    """Internal verification that the exact object was registered by RiskEngine."""
    with _lock:
        return id(decision) in _approved_decision_ids

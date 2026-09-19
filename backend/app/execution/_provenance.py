import threading
import weakref
from typing import Any

# A dictionary keyed by object ID with weak references as values.
# This safely tracks object identity for unhashable Pydantic models
# without retaining them in memory forever.
_lock = threading.Lock()
_registry: "weakref.WeakValueDictionary[int, Any]" = weakref.WeakValueDictionary()

def _register_approved_decision(decision: Any) -> None:
    """Internal registration of a genuine RiskEngine approved decision by exact object identity."""
    with _lock:
        _registry[id(decision)] = decision

def _verify_exact_decision_provenance(decision: Any) -> bool:
    """Internal verification that the exact object was registered by RiskEngine."""
    with _lock:
        registered_obj = _registry.get(id(decision))
        return registered_obj is decision

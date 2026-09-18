from app.schemas.execution import ExecutionResult
from app.schemas.order import OrderIntent
from app.execution.adapter import ExecutionAdapter


class ExecutionError(Exception):
    """Base exception for execution engine errors."""


class ExecutionEngine:
    """Orchestrates execution of an OrderIntent via a registered adapter.
    
    The ExecutionEngine treats OrderIntent as the sole input authority and does not mutate it.
    """
    
    def __init__(self, adapter: ExecutionAdapter):
        self.adapter = adapter

    def submit_intent(self, intent: OrderIntent) -> ExecutionResult:
        """Submit an OrderIntent for execution.
        
        The intent is structurally valid if it is a Pydantic OrderIntent model.
        The engine relies completely on the adapter for deterministic execution.
        """
        # Validate that we have an intent
        if not isinstance(intent, OrderIntent):
            raise ExecutionError("Invalid input: must be an OrderIntent.")
            
        # Call the configured adapter
        return self.adapter.execute(intent)

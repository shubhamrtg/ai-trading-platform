from app.execution.adapter import ExecutionAdapter
from app.execution.intent import ExecutableOrderIntent
from app.schemas.execution import ExecutionResult
from app.schemas.order import OrderIntent


class ExecutionError(Exception):
    """Raised for fundamental execution orchestrator failures."""


class ExecutionEngine:
    """Orchestrates order execution by routing intents to the appropriate adapter.

    The ExecutionEngine treats the ExecutableOrderIntent as an immutable authority.
    It does NOT run risk checks or calculate position sizing, but strictly ensures
    that only approved intents enter the execution layer.
    """

    def __init__(self, adapter: ExecutionAdapter):
        self.adapter = adapter

    def submit_intent(self, executable_intent: ExecutableOrderIntent) -> ExecutionResult:
        """Route an executable intent to the adapter.

        The execution engine requires an ExecutableOrderIntent to prove provenance
        from an APPROVED RiskDecision.
        """
        if not isinstance(executable_intent, ExecutableOrderIntent):
            raise ExecutionError("ExecutionEngine requires a trustworthy ExecutableOrderIntent.")

        intent = executable_intent.intent

        # Validate that we have an intent
        if not isinstance(intent, OrderIntent):
            raise ExecutionError("Invalid input: must be an OrderIntent.")

        # Call the configured adapter
        return self.adapter.execute(intent)

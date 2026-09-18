import abc

from app.schemas.execution import ExecutionResult
from app.schemas.order import OrderIntent


class ExecutionAdapter(abc.ABC):
    """Abstract interface for execution providers."""

    @property
    @abc.abstractmethod
    def adapter_identity(self) -> str:
        """Return the identity of the adapter."""
        pass

    @abc.abstractmethod
    def execute(self, intent: OrderIntent) -> ExecutionResult:
        """Execute the order intent and return the result."""
        pass

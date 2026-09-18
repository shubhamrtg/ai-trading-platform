from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.order import OrderIntent

class ApprovedRiskCapability(ABC):
    """
    Application-layer trust boundary for execution authority.
    The concrete capability is securely enclosed inside the RiskEngine
    evaluation path. It cannot be manufactured by arbitrary callers.
    """
    
    @abstractmethod
    def validate_intent(self, intent: 'OrderIntent') -> None:
        """Validates the intent against the approved immutable risk state."""
        raise NotImplementedError

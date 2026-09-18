import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from app.models.base import HistoricalDataIncompleteError
from app.models.enums import OrderSide, RiskDecisionStatus, SignalType
from app.models.trading import RiskDecisionModel, SignalModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_legacy_signal_handled_explicitly(db_session: AsyncSession) -> None:
    # 1. Create a legacy signal missing order_type
    sig_id = uuid.uuid4()
    legacy_signal = SignalModel(
        signal_id=sig_id,
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC/USD",
        timeframe="1h",
        side=OrderSide.BUY.value,
        signal_type=SignalType.ENTRY.value,
        proposed_entry_price=Decimal("50000.0"),
        order_type=None,  # Explicitly NULL for legacy
        timestamp=datetime.now()
    )
    db_session.add(legacy_signal)
    await db_session.commit()

    # 2. Fetch it back
    fetched = (await db_session.execute(select(SignalModel).where(SignalModel.signal_id == sig_id))).scalar_one()

    # 3. Ensure it cannot convert to domain and fail explicitly
    with pytest.raises(HistoricalDataIncompleteError, match="Legacy Signal lacks order_type"):
        fetched.to_domain()


@pytest.mark.asyncio
async def test_legacy_risk_decision_handled_explicitly(db_session: AsyncSession) -> None:
    # Setup parent signal
    sig_id = uuid.uuid4()
    corr_id = uuid.uuid4()
    base_signal = SignalModel(
        signal_id=sig_id,
        correlation_id=corr_id,
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC/USD",
        timeframe="1h",
        side=OrderSide.BUY.value,
        signal_type=SignalType.ENTRY.value,
        order_type="MARKET",
        timestamp=datetime.now()
    )
    db_session.add(base_signal)
    await db_session.commit()

    # 1. Create legacy risk decision missing trading_mode
    dec_id = uuid.uuid4()
    legacy_decision = RiskDecisionModel(
        decision_id=dec_id,
        correlation_id=corr_id,
        signal_id=sig_id,
        status=RiskDecisionStatus.APPROVED.value,
        trading_mode=None, # Explicitly NULL
        timestamp=datetime.now()
    )
    db_session.add(legacy_decision)
    await db_session.commit()

    # 2. Fetch it
    fetched = (await db_session.execute(select(RiskDecisionModel).where(RiskDecisionModel.decision_id == dec_id))).scalar_one()

    # 3. Ensure it fails explicitly
    with pytest.raises(HistoricalDataIncompleteError, match="Legacy RiskDecision lacks trading_mode"):
        fetched.to_domain()


@pytest.mark.asyncio
async def test_current_models_load_correctly(db_session: AsyncSession) -> None:
    sig_id = uuid.uuid4()
    corr_id = uuid.uuid4()
    signal = SignalModel(
        signal_id=sig_id,
        correlation_id=corr_id,
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC/USD",
        timeframe="1h",
        side=OrderSide.BUY.value,
        signal_type=SignalType.ENTRY.value,
        order_type="LIMIT",
        proposed_entry_price=Decimal("50000.0"),
        quantity=Decimal("1.5"),
        timestamp=datetime.now()
    )
    db_session.add(signal)
    await db_session.flush()

    dec_id = uuid.uuid4()
    decision = RiskDecisionModel(
        decision_id=dec_id,
        correlation_id=corr_id,
        signal_id=sig_id,
        status=RiskDecisionStatus.APPROVED.value,
        trading_mode="PAPER",
        risk_policy_version="1.0",
        calculated_quantity=Decimal("1.5"),
        timestamp=datetime.now()
    )
    db_session.add(decision)
    await db_session.commit()

    fetched_sig = (await db_session.execute(select(SignalModel).where(SignalModel.signal_id == sig_id))).scalar_one()
    fetched_dec = (await db_session.execute(select(RiskDecisionModel).where(RiskDecisionModel.decision_id == dec_id))).scalar_one()

    # Domain conversion should succeed
    domain_sig = fetched_sig.to_domain()
    domain_dec = fetched_dec.to_domain()

    assert domain_sig.order_type.value == "LIMIT"
    assert domain_dec.trading_mode.value == "PAPER"

@pytest.mark.asyncio
async def test_legacy_signal_lacks_quantity(db_session: AsyncSession) -> None:
    sig_id = uuid.uuid4()
    signal = SignalModel(
        signal_id=sig_id,
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC/USD",
        timeframe="1h",
        side=OrderSide.BUY.value,
        signal_type=SignalType.ENTRY.value,
        order_type="LIMIT",
        proposed_entry_price=Decimal("50000.0"),
        timestamp=datetime.now()
        # Missing quantity
    )
    db_session.add(signal)
    await db_session.commit()

    fetched = (await db_session.execute(select(SignalModel).where(SignalModel.signal_id == sig_id))).scalar_one()

    with pytest.raises(HistoricalDataIncompleteError, match="Legacy Signal lacks quantity"):
        fetched.to_domain()

@pytest.mark.asyncio
async def test_legacy_risk_decision_lacks_risk_policy_version(db_session: AsyncSession) -> None:
    sig_id = uuid.uuid4()
    signal = SignalModel(
        signal_id=sig_id,
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC/USD",
        timeframe="1h",
        side=OrderSide.BUY.value,
        signal_type=SignalType.ENTRY.value,
        order_type="LIMIT",
        quantity=Decimal("1.0"),
        timestamp=datetime.now()
    )
    db_session.add(signal)
    await db_session.flush()

    dec_id = uuid.uuid4()
    decision = RiskDecisionModel(
        decision_id=dec_id,
        correlation_id=uuid.uuid4(),
        signal_id=sig_id,
        status=RiskDecisionStatus.APPROVED.value,
        trading_mode="PAPER",
        calculated_quantity=Decimal("1.5"),
        timestamp=datetime.now()
        # Missing risk_policy_version
    )
    db_session.add(decision)
    await db_session.commit()

    fetched = (await db_session.execute(select(RiskDecisionModel).where(RiskDecisionModel.decision_id == dec_id))).scalar_one()

    with pytest.raises(HistoricalDataIncompleteError, match="Legacy RiskDecision lacks risk_policy_version"):
        fetched.to_domain()

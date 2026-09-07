import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.base import Base
# Import all models to ensure they are registered with Base
from app.models import *

@pytest.mark.asyncio
async def test_sqlalchemy_metadata():
    """Verify that all models can be created in an in-memory SQLite database.
    This ensures no foreign key or mapping errors exist.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # If we get here without an exception, mappings are valid.
    assert True

import logging
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sql import models

logger = logging.getLogger(__name__)

async def init_db(session: AsyncSession):
    logger.info("🔧 Inicializando datos base...")
    
    result = await session.execute(
        select(models.CustomerWallet).where(models.CustomerWallet.user_id == 1)
    )
    admin_wallet = result.scalar_one_or_none()
    
    if not admin_wallet:
        admin_wallet = models.CustomerWallet(user_id=1, amount=0, currency="EUR")
        session.add(admin_wallet)
        await session.commit()
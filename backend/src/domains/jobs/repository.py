from sqlalchemy.ext.asyncio import AsyncSession
from src.common.repository import BaseSQLAlchemyRepository
from src.domains.jobs.models import TranslationJob

class JobRepository(BaseSQLAlchemyRepository[TranslationJob]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, TranslationJob)

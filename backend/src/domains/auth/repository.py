from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.common.repository import BaseSQLAlchemyRepository
from src.domains.auth.models import User

class UserRepository(BaseSQLAlchemyRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, User)

    async def find_by_email(self, email: str) -> Optional[User]:
        query = select(User).where(User.email == email)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

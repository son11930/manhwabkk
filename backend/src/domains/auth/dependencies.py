from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db_session
from src.domains.auth.repository import UserRepository
from src.domains.auth.models import User
from src.common.security import decode_access_token
from src.common.exceptions import UnauthorizedError, ForbiddenError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db_session)
) -> User:
    payload = decode_access_token(token)
    user_id: str = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token payload.")
    
    repo = UserRepository(session)
    user = await repo.find_by_id(user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or inactive.")
    return user

async def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_super_admin:
        raise ForbiddenError("Only Super Admin can perform this action.")
    return current_user

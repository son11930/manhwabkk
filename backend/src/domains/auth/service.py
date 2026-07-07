from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from src.domains.auth.repository import UserRepository
from src.domains.auth.models import User
from src.domains.auth.schemas import UserCreateReq, UserLoginReq, TokenRes, UserRes
from src.common.security import get_password_hash, verify_password, create_access_token
from src.common.exceptions import UnauthorizedError, ValidationError
from src.config import settings

class AuthService:
    def __init__(self, session: AsyncSession):
        self.repo = UserRepository(session)

    async def initialize_super_admin(self) -> Optional[User]:
        """Creates default Super Admin if not exists."""
        admin = await self.repo.find_by_email(settings.SUPER_ADMIN_EMAIL)
        if not admin:
            admin = await self.repo.create({
                "email": settings.SUPER_ADMIN_EMAIL,
                "hashed_password": get_password_hash(settings.SUPER_ADMIN_PASSWORD),
                "is_active": True,
                "is_super_admin": True
            })
        return admin

    async def register(self, req: UserCreateReq) -> User:
        existing = await self.repo.find_by_email(req.email)
        if existing:
            raise ValidationError(f"Email '{req.email}' is already registered.")
        
        return await self.repo.create({
            "email": req.email,
            "hashed_password": get_password_hash(req.password),
            "is_active": True,
            "is_super_admin": req.is_super_admin
        })

    async def login(self, req: UserLoginReq) -> TokenRes:
        user = await self.repo.find_by_email(req.email)
        if not user or not verify_password(req.password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password.")
        if not user.is_active:
            raise UnauthorizedError("User account is disabled.")

        access_token = create_access_token(data={"sub": user.id, "is_admin": user.is_super_admin})
        return TokenRes(
            access_token=access_token,
            user=UserRes.model_validate(user)
        )

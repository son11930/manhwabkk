from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db_session
from src.domains.auth.service import AuthService
from src.domains.auth.schemas import UserCreateReq, UserLoginReq, TokenRes, UserRes
from src.domains.auth.dependencies import get_current_user, require_super_admin
from src.domains.auth.models import User
from src.common.envelope import APIResponse, success_response

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/register", response_model=APIResponse[UserRes])
async def register_user(req: UserCreateReq, session: AsyncSession = Depends(get_db_session)):
    service = AuthService(session)
    user = await service.register(req)
    return success_response(UserRes.model_validate(user))

@router.post("/login", response_model=APIResponse[TokenRes])
async def login_user(req: UserLoginReq, session: AsyncSession = Depends(get_db_session)):
    service = AuthService(session)
    token_res = await service.login(req)
    return success_response(token_res)

@router.get("/me", response_model=APIResponse[UserRes])
async def get_me(current_user: User = Depends(get_current_user)):
    return success_response(UserRes.model_validate(current_user))

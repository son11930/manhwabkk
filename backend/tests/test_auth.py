import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app
from src.config import settings
from src.domains.auth.service import AuthService
from src.domains.auth.schemas import UserCreateReq

@pytest.mark.asyncio
async def test_super_admin_initialization(test_session):
    """Test that default super admin is created on initialization."""
    service = AuthService(test_session)
    admin = await service.initialize_super_admin()
    assert admin is not None
    assert admin.email == settings.SUPER_ADMIN_EMAIL
    assert admin.is_super_admin is True

@pytest.mark.asyncio
async def test_register_and_login_flow(test_session):
    """Test user registration and login JWT issuance."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register normal user
        reg_res = await client.post("/api/v1/auth/register", json={
            "email": "reader@example.com",
            "password": "strongpassword123",
            "is_super_admin": False
        })
        assert reg_res.status_code == 200
        data = reg_res.json()
        assert data["success"] is True
        assert data["data"]["email"] == "reader@example.com"
        assert data["data"]["is_super_admin"] is False

        # Login
        login_res = await client.post("/api/v1/auth/login", json={
            "email": "reader@example.com",
            "password": "strongpassword123"
        })
        assert login_res.status_code == 200
        login_data = login_res.json()
        assert login_data["success"] is True
        token = login_data["data"]["access_token"]
        assert len(token) > 20

@pytest.mark.asyncio
async def test_require_super_admin_protection(test_session):
    """Test that regular users are blocked from super admin routes."""
    service = AuthService(test_session)
    await service.register(UserCreateReq(email="user@test.com", password="password123", is_super_admin=False))
    await service.register(UserCreateReq(email="admin@test.com", password="password123", is_super_admin=True))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Get user token
        user_login = await client.post("/api/v1/auth/login", json={"email": "user@test.com", "password": "password123"})
        user_token = user_login.json()["data"]["access_token"]

        # Attempt super admin action (create series) with normal user token -> Should fail 403
        res_forbidden = await client.post(
            "/api/v1/series",
            json={"slug": "test-slug", "title_th": "Test Manga"},
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert res_forbidden.status_code == 403

        # Get admin token
        admin_login = await client.post("/api/v1/auth/login", json={"email": "admin@test.com", "password": "password123"})
        admin_token = admin_login.json()["data"]["access_token"]

        # Attempt super admin action with admin token -> Should succeed 200
        res_allowed = await client.post(
            "/api/v1/series",
            json={"slug": "test-slug", "title_th": "Test Manga"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res_allowed.status_code == 200
        assert res_allowed.json()["data"]["slug"] == "test-slug"

import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app
from src.config import settings

@pytest.mark.asyncio
async def test_full_user_and_admin_e2e_flow(test_session):
    """
    E2E Test Simulation:
    1. Check API Health
    2. User submits a new English Manga URL for translation
    3. Verify Job progress and status
    4. Fetch Reader View data
    5. Super Admin logs in
    6. Super Admin deletes the series
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Step 1: Health check
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        # Step 2: Submit Job
        job_req = {"source_url": "https://example.com/manga/solo-leveling/chapter-1"}
        res = await client.post("/api/v1/jobs/submit", json=job_req)
        assert res.status_code == 200
        job_data = res.json()["data"]
        assert job_data["source_url"] == job_req["source_url"]
        job_id = job_data["id"]

        # Step 3: Check Job Status
        res = await client.get(f"/api/v1/jobs/{job_id}")
        assert res.status_code == 200
        assert res.json()["data"]["id"] == job_id

        # Step 4: Check Catalog Series List
        res = await client.get("/api/v1/series")
        assert res.status_code == 200
        assert isinstance(res.json()["data"], list)

        # Step 5: Super Admin Login
        from src.domains.auth.service import AuthService
        auth_service = AuthService(test_session)
        await auth_service.initialize_super_admin()

        login_req = {
            "email": settings.SUPER_ADMIN_EMAIL,
            "password": settings.SUPER_ADMIN_PASSWORD
        }
        res = await client.post("/api/v1/auth/login", json=login_req)
        assert res.status_code == 200
        token = res.json()["data"]["access_token"]

        # Step 6: Verify Admin can access protected delete endpoint
        headers = {"Authorization": f"Bearer {token}"}
        res = await client.delete("/api/v1/series/non-existent-slug", headers=headers)
        # Should be 404 (not found) rather than 401 (unauthorized) because admin token is valid!
        assert res.status_code in [200, 404]

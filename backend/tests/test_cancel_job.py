import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app

@pytest.mark.asyncio
async def test_cancel_job_endpoint(test_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Submit job
        res = await client.post("/api/v1/jobs/submit", json={
            "source_url": "https://asuracomic.net/comics/infinite-mage/chapter/176",
            "translation_provider": "groq"
        })
        assert res.status_code == 200
        job_id = res.json()["data"]["id"]

        # Cancel job
        cancel_res = await client.post(f"/api/v1/jobs/{job_id}/cancel")
        assert cancel_res.status_code == 200
        assert cancel_res.json()["data"]["status"] == "CANCELLED"

        # Get job status
        get_res = await client.get(f"/api/v1/jobs/{job_id}")
        assert get_res.status_code == 200
        assert get_res.json()["data"]["status"] == "CANCELLED"

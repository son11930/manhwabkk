import pytest
from pydantic import ValidationError
from src.domains.jobs.schemas import JobSubmitReq, JobStatusRes, TranslationProvider
from src.domains.jobs.models import TranslationJob
from src.config import settings


def test_translation_provider_enum_values():
    assert TranslationProvider.GROQ == "groq"
    assert TranslationProvider.DEEPSEEK_V4_FLASH == "deepseek-v4-flash"
    assert TranslationProvider.DEEPSEEK_V4_PRO == "deepseek-v4-pro"
    assert TranslationProvider.DEEPSEEK_CHAT == "deepseek-chat"


def test_job_submit_req_default_provider():
    req = JobSubmitReq(source_url="https://example.com/chapter-1")
    assert req.translation_provider == TranslationProvider.GROQ


def test_job_submit_req_explicit_providers():
    for provider in [
        TranslationProvider.GROQ,
        TranslationProvider.DEEPSEEK_V4_FLASH,
        TranslationProvider.DEEPSEEK_V4_PRO,
        TranslationProvider.DEEPSEEK_CHAT,
    ]:
        req = JobSubmitReq(
            source_url="https://example.com/chapter-1",
            translation_provider=provider,
        )
        assert req.translation_provider == provider


def test_job_submit_req_invalid_provider():
    with pytest.raises(ValidationError):
        JobSubmitReq(
            source_url="https://example.com/chapter-1",
            translation_provider="invalid-provider",
        )


def test_translation_job_model_new_fields():
    job = TranslationJob(
        source_url="https://example.com/chapter-1",
        translation_provider=TranslationProvider.DEEPSEEK_V4_FLASH.value,
        requested_model="deepseek-chat",
        actual_model="deepseek-chat",
        input_tokens=1500,
        output_tokens=300,
        cost_estimate_usd=0.015,
    )
    assert job.translation_provider == "deepseek-v4-flash"
    assert job.requested_model == "deepseek-chat"
    assert job.actual_model == "deepseek-chat"
    assert job.input_tokens == 1500
    assert job.output_tokens == 300
    assert job.cost_estimate_usd == 0.015


def test_config_separated_groq_and_deepseek_settings():
    # Verify Groq settings exist independently
    assert hasattr(settings, "GROQ_API_KEY")
    assert hasattr(settings, "GROQ_MODEL")

    # Verify DeepSeek settings exist independently without impacting Groq
    assert hasattr(settings, "DEEPSEEK_API_KEY")
    assert hasattr(settings, "DEEPSEEK_API_BASE_URL")
    assert hasattr(settings, "DEEPSEEK_BATCH_PAGES")
    assert settings.DEEPSEEK_BATCH_PAGES == 5
    assert settings.DEEPSEEK_MAX_BATCH_SEGMENTS == 80
    assert settings.DEEPSEEK_MAX_BATCH_INPUT_CHARS == 120000
    assert settings.DEEPSEEK_TIMEOUT_SECONDS == 90
    assert settings.DEEPSEEK_MAX_RETRIES == 2


@pytest.mark.asyncio
async def test_service_submit_job_stores_provider():
    from unittest.mock import AsyncMock, MagicMock
    from src.domains.jobs.service import JobService

    mock_session = MagicMock()
    service = JobService(mock_session)
    service.repo.create = AsyncMock(
        side_effect=lambda data: TranslationJob(
            id="test-job",
            source_url=data["source_url"],
            translation_provider=data["translation_provider"],
        )
    )

    req = JobSubmitReq(
        source_url="https://example.com/ch1",
        translation_provider=TranslationProvider.DEEPSEEK_CHAT,
    )
    job = await service.submit_job(req)
    assert job.translation_provider == "deepseek-chat"


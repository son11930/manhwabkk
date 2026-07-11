import json
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.translation.models import TranslationArtifact, TranslationProfile


class TranslationProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def latest(self, series_id: str) -> TranslationProfile | None:
        result = await self.session.execute(
            select(TranslationProfile)
            .where(TranslationProfile.series_id == series_id)
            .order_by(TranslationProfile.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def append(self, series_id: str, profile: dict[str, Any], source: str) -> TranslationProfile:
        latest = await self.latest(series_id)
        record = TranslationProfile(
            series_id=series_id,
            version=(latest.version + 1) if latest else 1,
            source=source,
            profile_json=json.dumps(profile, ensure_ascii=False),
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record


class TranslationArtifactRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def append_many(self, artifacts: Iterable[dict[str, Any]]) -> None:
        self.session.add_all([TranslationArtifact(**artifact) for artifact in artifacts])
        await self.session.commit()

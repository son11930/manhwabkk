from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from collections.abc import Callable, Mapping, Sequence
from typing import Optional
import uuid
import time

logger = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.jobs.models import TranslationJob
from src.domains.jobs.repository import JobRepository
from src.domains.manga.repository import ChapterRepository, PageRepository, SeriesRepository
from src.domains.translation.repository import TranslationArtifactRepository
from src.domains.translation.repository import TranslationProfileRepository
from src.infrastructure.scraper.scraper_service import ScraperService
from src.infrastructure.storage.r2_service import R2StorageService
from src.pipeline.contracts import OCRSegment, TranslationBatchRequest, TranslationResult
from src.pipeline.inpainter import InpainterEngine
from src.pipeline.ocr import MangaOCREngine
from src.pipeline.quality import TranslationQualityGate
from src.pipeline.rendering import (
    RenderInstruction,
    associate_shifted_region_candidates,
    build_render_instructions,
    deduplicate_render_instructions,
)
from src.pipeline.translator import AITranslatorEngine, TranslationResponseError
from src.infrastructure.ai.factory import get_ai_client
from src.pipeline.deepseek_batch_translator import DeepSeekBatchTranslator, append_batch_context, group_pages_for_batching
from src.pipeline.typesetter import TypesetterEngine
from src.config import settings


_SPARE_ME_GREAT_LORD_GLOSSARY = (
    {"source": "Dragnet", "thai": "เครือข่ายสวรรค์", "locked": True},
    {"source": "Lu Shu", "thai": "ลู่ซู", "locked": True},
    {"source": "Lu Xiaoyu", "thai": "ลู่เสี่ยวอวี๋", "locked": True},
    {"source": "families", "thai": "ตระกูล", "locked": True},
    {"source": "great families", "thai": "ตระกูลใหญ่", "locked": True},
    {"source": "family", "thai": "ตระกูล", "locked": True},
    {"source": "clan", "thai": "ตระกูล", "locked": True},
    {"source": "water-type", "thai": "ผู้ใช้พลังธาตุน้ำ", "locked": True},
    {"source": "water type", "thai": "ผู้ใช้พลังธาตุน้ำ", "locked": True},
    {"source": "I am a water-type", "thai": "ฉันเป็นผู้ใช้พลังธาตุน้ำ", "locked": True},
    {"source": "I'm a water-type", "thai": "ฉันเป็นผู้ใช้พลังธาตุน้ำ", "locked": True},
    {"source": "NEGATIVE EMOTION VALUE", "thai": "แต้มอารมณ์ด้านลบ", "locked": True},
    {"source": "Li Yixiao", "thai": "หลี่อี้เซี่ยว", "locked": True},
    {"source": "flying dagger", "thai": "มีดบิน", "locked": True},
    {"source": "little flying dagger", "thai": "มีดบินเล็ก", "locked": True},
    {"source": "ruins", "thai": "ซากปรักหักพัง", "locked": True},
)

_MANDATORY_RECOVERY_ISSUES = frozenset({
    "EMPTY_TRANSLATION",
    "ENGLISH_LEAKAGE",
    "META_TEXT",
})


class TranslationPipelineWorker:
    """Chapter-aware translation worker with safe staged publishing."""

    def __init__(
        self,
        session: AsyncSession,
        scraper: Optional[ScraperService] = None,
        ocr: Optional[MangaOCREngine] = None,
        inpainter: Optional[InpainterEngine] = None,
        translator: Optional[AITranslatorEngine] = None,
        typesetter: Optional[TypesetterEngine] = None,
        r2_service: Optional[R2StorageService] = None,
        quality_gate: Optional[TranslationQualityGate] = None,
        profile: Optional[Mapping[str, object]] = None,
        glossary: Sequence[Mapping[str, object]] = (),
        run_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ):
        self.session = session
        self.job_repo = JobRepository(session)
        self.series_repo = SeriesRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.page_repo = PageRepository(session)
        self.artifact_repo = TranslationArtifactRepository(session)
        self.profile_repo = TranslationProfileRepository(session)
        self.scraper = scraper or ScraperService()
        self.ocr = ocr or MangaOCREngine()
        self.inpainter = inpainter or InpainterEngine()
        self.translator = translator or AITranslatorEngine()
        self.typesetter = typesetter or TypesetterEngine()
        self.r2_service = r2_service or R2StorageService()
        self.quality_gate = quality_gate or TranslationQualityGate()
        self.profile = dict(profile) if profile else None
        self.glossary = tuple(glossary)
        self.run_id_factory = run_id_factory
        import os
        cpu_count = os.cpu_count() or 2
        max_workers = max(2, min(4, cpu_count // 2))
        self.cpu_semaphore = asyncio.Semaphore(max_workers)
        self.upload_semaphore = asyncio.Semaphore(10)
        self.db_lock = asyncio.Lock()

    async def _profile_for(self, series_id: str, series_slug: str) -> tuple[dict[str, object], tuple[Mapping[str, object], ...]]:
        if self.profile:
            return self.profile, self.glossary
        profile = self.profile or {"genre": "neutral", "style": {"register": "conversational"}}
        glossary = self.glossary
        if not glossary and series_slug == "spare-me-great-lord":
            glossary = _SPARE_ME_GREAT_LORD_GLOSSARY
        latest = await self.profile_repo.latest(series_id)
        if latest:
            stored = json.loads(latest.profile_json)
            profile = stored.get("profile", profile)
            glossary = tuple(stored.get("glossary", glossary))
        else:
            await self.profile_repo.append(
                series_id,
                {"profile": profile, "glossary": list(glossary)},
                source="seed" if glossary else "default",
            )
        return profile, glossary

    @staticmethod
    def _segments_from_ocr(page_index: int, items: Sequence[object]) -> tuple[OCRSegment, ...]:
        """Accept the new OCR contract while remaining compatible with legacy OCR adapters."""
        segments: list[OCRSegment] = []
        for order, item in enumerate(items, start=1):
            if isinstance(item, OCRSegment):
                segments.append(item)
                continue
            if not isinstance(item, Mapping):
                raise TypeError("OCR output must be OCRSegment or mapping")
            source_text = str(item.get("source_text") or item.get("text") or "").strip()
            box = tuple(item.get("box", (0, 0, 0, 0)))
            if len(box) != 4:
                raise ValueError("legacy OCR output has an invalid box")
            segments.append(OCRSegment(
                segment_id=f"{page_index}:{order}",
                page_index=page_index,
                reading_order=order,
                box=box,
                raw_lines=tuple(item.get("raw_lines") or (source_text,)),
                source_text=source_text,
                confidence=float(item.get("confidence", 1.0)),
            ))
        return tuple(segments)

    @staticmethod
    def _deduplicate_pages(pages: Sequence[dict]) -> list[dict]:
        seen_urls: set[str] = set()
        unique_pages: list[dict] = []
        for page in pages:
            raw_url = page.get("raw_url", "")
            if raw_url and raw_url in seen_urls:
                continue
            if raw_url:
                seen_urls.add(raw_url)
            unique_pages.append(page)
        return unique_pages

    async def _record_artifacts(
        self,
        run_id: str,
        job_id: str,
        chapter_id: str,
        results: Sequence[TranslationResult],
        segments: Mapping[str, OCRSegment],
    ) -> None:
        artifacts = []
        for result in results:
            segment = segments[result.segment_id]
            artifacts.append({
                "run_id": run_id,
                "job_id": job_id,
                "chapter_id": chapter_id,
                "page_index": segment.page_index,
                "segment_id": segment.segment_id,
                "source_text": segment.source_text,
                "raw_lines_json": json.dumps(segment.raw_lines, ensure_ascii=False),
                "ocr_confidence": segment.confidence,
                "draft_text": result.draft_thai,
                "final_text": result.final_thai,
                "qc_status": result.qc_status,
                "issue_codes_json": json.dumps(result.issue_codes, ensure_ascii=False),
                "model_name": result.model,
                "attempts": result.attempts,
            })
        if artifacts:
            await self.artifact_repo.append_many(artifacts)

    async def _cancelled_job(self, job_id: str) -> Optional[TranslationJob]:
        """Return the current job only when cancellation was requested."""
        current_job = await self.job_repo.find_by_id(job_id)
        return current_job if current_job and current_job.status == "CANCELLED" else None

    async def process_job(
        self,
        job_id: str,
        *,
        publish: bool = True,
        ai_client: Optional[Any] = None,
    ) -> TranslationJob:
        job = await self.job_repo.find_by_id(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found.")

        if job.status == "CANCELLED":
            logger.info("[Worker] Job %s is already CANCELLED. Skipping processing.", job_id)
            return job

        job_start = time.perf_counter()
        logger.info("[Worker] Starting translation job %s for URL: %s", job_id, job.source_url)
        try:
            await self.job_repo.update(job_id, {"status": "SCRAPING", "progress_percent": 10})
            data = await self.scraper.fetch_chapter_data(job.source_url)
            if not data or not data.get("pages"):
                raise ValueError("ไม่พบรูปภาพในลิงก์การ์ตูนนี้")

            series_slug = data["series_slug"]
            chapter_number = data["chapter_number"]
            pages_data = sorted(self._deduplicate_pages(data["pages"]), key=lambda page: page["index"])
            logger.info("[Worker] Job %s scraped %d pages for series '%s' chapter '%s'", job_id, len(pages_data), series_slug, chapter_number)
            await self.job_repo.update(job_id, {
                "manga_slug": series_slug,
                "chapter_number": chapter_number,
                "status": "TRANSLATING",
                "progress_percent": 30,
            })

            series = await self.series_repo.find_by_slug(series_slug)
            if not series:
                series = await self.series_repo.create({
                    "slug": series_slug,
                    "title_th": data["series_title"],
                    "source_url": job.source_url,
                })
            chapter = await self.chapter_repo.find_by_series_and_number(series.id, chapter_number)
            if not chapter:
                chapter = await self.chapter_repo.create({
                    "series_id": series.id,
                    "chapter_number": chapter_number,
                    "title_th": f"Chapter {chapter_number}",
                    "source_url": job.source_url,
                    "next_chapter_url": data.get("next_chapter_url"),
                    "prev_chapter_url": data.get("prev_chapter_url"),
                    "is_translated": False,
                })

            stage_ocr_start = time.perf_counter()
            logger.info("[Worker] [Job %s] === STAGE 1/4: OCR Extraction started across %d pages ===", job_id, len(pages_data))
            current_job = await self._cancelled_job(job_id)
            if current_job:
                logger.info("[Worker] Job %s cancelled during OCR phase", job_id)
                return current_job

            async def _extract_page_ocr(page: dict) -> tuple[int, list]:
                queued_at = time.perf_counter()
                async with self.cpu_semaphore:
                    started_at = time.perf_counter()
                    batch = await self.ocr.detect_and_extract(page["image_bytes"], page_index=page["index"])
                finished_at = time.perf_counter()
                logger.info(
                    "[Worker] [Job %s] OCR Page %d/%d done in %.2fs (queue %.2fs, OCR %.2fs, found %d bubbles)",
                    job_id,
                    page["index"],
                    len(pages_data),
                    finished_at - queued_at,
                    started_at - queued_at,
                    finished_at - started_at,
                    len(batch),
                )
                return page["index"], batch

            ocr_results = await asyncio.gather(*[_extract_page_ocr(p) for p in pages_data])
            current_job = await self._cancelled_job(job_id)
            if current_job:
                logger.info("[Worker] Job %s cancelled after OCR; discarding results", job_id)
                return current_job
            for completed_ocr_count, res in enumerate(ocr_results, start=1):
                ocr_prog = 30 + int((completed_ocr_count / max(1, len(pages_data))) * 15)
                await self.job_repo.update(job_id, {"progress_percent": ocr_prog})
            ocr_batches = [batch for _, batch in ocr_results]

            ocr_duration = time.perf_counter() - stage_ocr_start
            logger.info("[Worker] [Job %s] === STAGE 1/4 DONE in %.2fs (avg %.2fs/page) across %d pages ===", job_id, ocr_duration, ocr_duration / max(1, len(pages_data)), len(pages_data))
            segments_by_page = {
                page["index"]: self._segments_from_ocr(page["index"], batch)
                for page, batch in zip(pages_data, ocr_batches)
            }
            profile, glossary = await self._profile_for(series.id, series_slug)
            run_id = self.run_id_factory()
            rolling_context: list[dict[str, str]] = []
            staged_pages: list[dict] = []
            all_results: list[TranslationResult] = []
            all_segments: dict[str, OCRSegment] = {}
            warnings = False
            provider = getattr(job, "translation_provider", "groq") or "groq"
            deepseek_translations: dict[str, str] = {}
            total_in_tokens = 0
            total_out_tokens = 0
            total_cost_usd = 0.0
            actual_model = ""
            active_ds_translator: Optional[DeepSeekBatchTranslator] = None

            if provider in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat"):
                client = ai_client or get_ai_client(provider)
                batch_translator = DeepSeekBatchTranslator(client=client, provider=provider)
                active_ds_translator = batch_translator
                ordered_page_segs = [segments_by_page[page["index"]] for page in pages_data]
                batches = group_pages_for_batching(
                    ordered_page_segs,
                    max_pages=settings.DEEPSEEK_BATCH_PAGES,
                    max_segments=settings.DEEPSEEK_MAX_BATCH_SEGMENTS,
                    max_chars=settings.DEEPSEEK_MAX_BATCH_INPUT_CHARS,
                )
                # Separate batch concurrency by provider tier with safety headroom
                if provider in ("deepseek-v4-flash", "deepseek-chat"):
                    batch_limit = 6
                elif provider in ("deepseek-v4-pro", "deepseek-reasoner"):
                    batch_limit = 3
                else:
                    batch_limit = 1

                stage_ai_start = time.perf_counter()
                logger.info(
                    "[Worker] [Job %s] === STAGE 2/4: serial contextual AI Batch Translation started (%d batches across %d pages, provider=%s, configured_provider_cap=%d) ===",
                    job_id, len(batches), len(pages_data), provider, batch_limit
                )

                async def translate_deepseek_batch(batch_idx: int, page_batch, context):
                    batch_start = time.perf_counter()
                    try:
                        res = await batch_translator.translate_page_batch(
                            page_batch,
                            glossary=tuple(glossary),
                            context=context,
                            genre=str(profile.get("genre", "modern_cultivation")) if isinstance(profile, dict) else "modern_cultivation",
                        )
                        missing_ids = res.parse_outcome.missing_ids if res.parse_outcome else ()
                        if missing_ids:
                            missing_id_set = set(missing_ids)
                            missing_segments = [
                                segment
                                for page in page_batch
                                for segment in page
                                if segment.segment_id in missing_id_set
                            ]
                            logger.warning(
                                "[Worker] [Job %s] Batch %d/%d preserved %d translations; recovering %d missing IDs only",
                                job_id, batch_idx, len(batches), len(res.translations), len(missing_segments),
                            )
                            try:
                                recovered = await batch_translator.translate_page_batch(
                                    [missing_segments],
                                    glossary=tuple(glossary),
                                    context=context,
                                    genre=str(profile.get("genre", "modern_cultivation")) if isinstance(profile, dict) else "modern_cultivation",
                                )
                                res = replace(
                                    res,
                                    translations={**res.translations, **recovered.translations},
                                    input_tokens=res.input_tokens + recovered.input_tokens,
                                    output_tokens=res.output_tokens + recovered.output_tokens,
                                    cost_usd=res.cost_usd + recovered.cost_usd,
                                )
                            except Exception as recovery_error:
                                logger.warning(
                                    "[Worker] [Job %s] Batch %d/%d missing-only recovery failed (%s); retaining valid partial translations",
                                    job_id, batch_idx, len(batches), type(recovery_error).__name__,
                                )
                    except Exception as first_error:
                        logger.warning(
                            "[Worker] [Job %s] Batch %d/%d attempt 1 failed (%s), retrying once...",
                            job_id, batch_idx, len(batches), type(first_error).__name__,
                        )
                        res = await batch_translator.translate_page_batch(
                            page_batch,
                            glossary=tuple(glossary),
                            context=context,
                            genre=str(profile.get("genre", "modern_cultivation")) if isinstance(profile, dict) else "modern_cultivation",
                        )
                    logger.info(
                        "[Worker] [Job %s] Batch %d/%d completed in %.2fs (%d segments translated)",
                        job_id, batch_idx, len(batches), time.perf_counter() - batch_start, len(res.translations)
                    )
                    return res

                for batch_idx, page_batch in enumerate(batches, start=1):
                    batch_context = tuple(rolling_context[-8:])
                    try:
                        batch_res = await translate_deepseek_batch(batch_idx, page_batch, batch_context)
                    except Exception as batch_error:
                        logger.warning("[Worker] [Job %s] DeepSeek batch translation failed: %s", job_id, type(batch_error).__name__)
                        continue
                    try:
                        deepseek_translations.update(batch_res.translations)
                        rolling_context = list(append_batch_context(batch_context, page_batch, batch_res.translations))
                        total_in_tokens += batch_res.input_tokens
                        total_out_tokens += batch_res.output_tokens
                        total_cost_usd += batch_res.cost_usd
                        actual_model = batch_res.model
                    except Exception as apply_err:
                        logger.warning("[Worker] [Job %s] DeepSeek batch result could not be applied: %s", job_id, apply_err)

                ai_duration = time.perf_counter() - stage_ai_start
                logger.info(
                    "[Worker] [Job %s] === STAGE 2/4 DONE in %.2fs (%d segments translated across %d batches) ===",
                    job_id, ai_duration, len(deepseek_translations), len(batches)
                )
                await self.job_repo.update(job_id, {"progress_percent": 60})

            current_job = await self._cancelled_job(job_id)
            if current_job:
                logger.info("[Worker] Job %s cancelled after translation; discarding results", job_id)
                return current_job

            stage_render_start = time.perf_counter()
            logger.info("[Worker] [Job %s] === STAGE 3/4: Page Processing started across %d pages ===", job_id, len(pages_data))

            for page in pages_data:
                page_segments = segments_by_page[page["index"]]
                all_segments.update({segment.segment_id: segment for segment in page_segments})

            page_render_jobs: list[tuple[dict, list]] = []
            for page in pages_data:
                current_job = await self._cancelled_job(job_id)
                if current_job:
                    logger.info("[Worker] Job %s cancelled during page processing", job_id)
                    return current_job
                page_segments = segments_by_page[page["index"]]
                approved: list[dict[str, object]] = []
                final_page_results: list[TranslationResult] = []
                page_warnings = False

                if provider in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat"):
                    for seg in page_segments:
                        translated_text = deepseek_translations.get(seg.segment_id, seg.source_text)
                        final_page_results.append(
                            TranslationResult(
                                segment_id=seg.segment_id,
                                source_text=seg.source_text,
                                draft_thai=translated_text,
                                final_thai=translated_text,
                                model=actual_model or "deepseek-chat",
                                attempts=1,
                                qc_status="APPROVED" if translated_text != seg.source_text else "NEEDS_REVIEW",
                                issue_codes=() if translated_text != seg.source_text else ("EMPTY_TRANSLATION",),
                            )
                        )
                else:
                    logger.info("[Worker] Job %s page %d translating %d segments with %s...", job_id, page["index"], len(page_segments), provider)
                    req = TranslationBatchRequest(
                        segments=tuple(page_segments),
                        profile=profile,
                        glossary=tuple(glossary),
                        context=tuple(rolling_context[-8:]),
                    )
                    batch_start = time.perf_counter()
                    try:
                        batch_results = await self.translator.translate_batch(req)
                    except Exception as batch_error:
                        logger.warning(
                            "[Worker] Job %s page %d batch translation failed (%s); recovering segments individually",
                            job_id, page["index"], type(batch_error).__name__,
                        )
                        batch_results = []
                    logger.info("[Worker] Job %s page %d translated in %.2fs", job_id, page["index"], time.perf_counter() - batch_start)
                    final_page_results.extend(batch_results)

                result_map = {res.segment_id: res for res in final_page_results}
                missing_on_page = [
                    s for s in page_segments
                    if s.segment_id not in result_map
                    or not result_map[s.segment_id].final_thai
                    or result_map[s.segment_id].final_thai.strip() == s.source_text.strip()
                    or bool(
                        _MANDATORY_RECOVERY_ISSUES
                        & set(self.quality_gate.evaluate(s, result_map[s.segment_id].final_thai, glossary).issue_codes)
                    )
                ]
                if missing_on_page and active_ds_translator is not None:
                    try:
                        logger.info("[Worker] [Job %s] Page %d batch recovering %d untranslated segments...", job_id, page["index"], len(missing_on_page))
                        page_rec_res = await active_ds_translator.translate_page_batch(
                            [missing_on_page],
                            glossary=tuple(glossary),
                            context=tuple(rolling_context[-8:]),
                            genre=str(profile.get("genre", "modern_cultivation")) if isinstance(profile, dict) else "modern_cultivation",
                        )
                        for s in missing_on_page:
                            th_val = page_rec_res.translations.get(s.segment_id, "")
                            if th_val and th_val.strip() != s.source_text.strip():
                                result_map[s.segment_id] = TranslationResult(
                                    segment_id=s.segment_id,
                                    source_text=s.source_text,
                                    draft_thai=th_val.strip(),
                                    final_thai=th_val.strip(),
                                    model=page_rec_res.model or "batch_page_recovery",
                                    attempts=2,
                                    qc_status="APPROVED",
                                    issue_codes=(),
                                )
                    except Exception as page_rec_err:
                        logger.warning("[Worker] [Job %s] Page %d batch recovery failed: %s", job_id, page["index"], page_rec_err)

                final_page_results = []
                for segment in page_segments:
                    result = result_map.get(segment.segment_id)
                    if result is None:
                        thai_val = ""
                        if provider not in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat"):
                            thai_val = await self.translator.translate_text(
                                segment.source_text,
                                genre=str(profile.get("genre", "modern_cultivation")) if isinstance(profile, dict) else "modern_cultivation",
                            )
                        success = bool(thai_val and thai_val != segment.source_text)
                        result = TranslationResult(
                            segment_id=segment.segment_id,
                            source_text=segment.source_text,
                            draft_thai=thai_val or segment.source_text,
                            final_thai=thai_val or segment.source_text,
                            model="single_fallback",
                            attempts=1,
                            qc_status="APPROVED" if success else "NEEDS_REVIEW",
                            issue_codes=() if success else ("EMPTY_TRANSLATION",),
                        )
                    assessment = self.quality_gate.evaluate(segment, result.final_thai, glossary)
                    needs_recovery = bool(set(assessment.issue_codes) & _MANDATORY_RECOVERY_ISSUES)
                    if needs_recovery and not assessment.passed and active_ds_translator is None:
                        review_profile = {
                            **profile,
                            "quality_review": (
                                "ตรวจ draft เทียบต้นฉบับให้ความหมายครบ ห้ามเพิ่มเหตุการณ์ "
                                "แก้เฉพาะเมื่อจำเป็น และตอบ JSON ตาม schema เดิมเท่านั้น"
                            ),
                            "draft_text": result.final_thai,
                            "quality_issue_codes": assessment.issue_codes,
                        }
                        review_request = TranslationBatchRequest(
                            segments=(segment,),
                            profile=review_profile,
                            glossary=tuple(glossary),
                            context=tuple(rolling_context[-6:]),
                        )
                        recovered = None
                        if active_ds_translator is not None:
                            try:
                                recovery_res = await active_ds_translator.translate_page_batch(
                                    [[segment]],
                                    glossary=tuple(glossary),
                                    context=tuple(rolling_context[-6:]),
                                    genre=str(review_profile.get("genre", "modern_cultivation")),
                                )
                                if segment.segment_id in recovery_res.translations:
                                    total_in_tokens += recovery_res.input_tokens
                                    total_out_tokens += recovery_res.output_tokens
                                    recovered = TranslationResult(
                                        segment_id=segment.segment_id,
                                        source_text=segment.source_text,
                                        draft_thai=recovery_res.translations[segment.segment_id],
                                        final_thai=recovery_res.translations[segment.segment_id],
                                        model=recovery_res.model,
                                        attempts=2,
                                        qc_status="APPROVED",
                                        issue_codes=(),
                                    )
                            except Exception as recovery_err:
                                logger.warning("[Worker] DeepSeek recovery translation failed for %s: %s", segment.segment_id, recovery_err)
                        else:
                            import inspect
                            from unittest.mock import AsyncMock
                            func = getattr(self.translator, "translate_batch_structured", None)
                            if func and (inspect.iscoroutinefunction(func) or isinstance(func, AsyncMock)):
                                reviewed = await func(review_request)
                                recovered = reviewed.results[0] if reviewed.results else None
                            else:
                                reviewed = await self.translator.translate_batch(review_request)
                                recovered = reviewed[0] if reviewed else None
                        if (
                            recovered
                            and recovered.final_thai
                            and recovered.final_thai.strip() != segment.source_text.strip()
                        ):
                            recovered_assessment = self.quality_gate.evaluate(
                                segment, recovered.final_thai, glossary
                            )
                            if recovered_assessment.passed or len(recovered_assessment.issue_codes) < len(assessment.issue_codes):
                                result = recovered
                                assessment = recovered_assessment
                        else:
                            assessment = type(assessment)(
                                passed=False,
                                issue_codes=tuple((*assessment.issue_codes, "INVALID_REVIEW_RESPONSE")),
                                requires_semantic_review=True,
                            )

                    if (
                        (not result.final_thai or result.final_thai.strip() == segment.source_text.strip())
                        and active_ds_translator is None
                    ):
                        try:
                            if active_ds_translator is not None:
                                em_res = await active_ds_translator.translate_page_batch(
                                    [[segment]],
                                    glossary=tuple(glossary),
                                    context=tuple(rolling_context[-6:]),
                                    genre=str(profile.get("genre", "modern_cultivation")) if isinstance(profile, dict) else "modern_cultivation",
                                )
                                emergency_thai = em_res.translations.get(segment.segment_id, "")
                            else:
                                emergency_thai = await self.translator.translate_text(
                                    segment.source_text,
                                    genre=str(profile.get("genre", "modern_cultivation")) if isinstance(profile, dict) else "modern_cultivation",
                                )
                            if emergency_thai and emergency_thai.strip() != segment.source_text.strip():
                                result = TranslationResult(
                                    segment_id=result.segment_id,
                                    source_text=result.source_text,
                                    draft_thai=result.draft_thai,
                                    final_thai=emergency_thai.strip(),
                                    model=result.model or "emergency_fallback",
                                    attempts=result.attempts + 1,
                                    qc_status="APPROVED",
                                    issue_codes=(),
                                )
                                assessment = self.quality_gate.evaluate(segment, result.final_thai, glossary)
                        except Exception as e:
                            logger.warning("[Worker] Emergency fallback translation failed for %s: %s", segment.segment_id, e)
                    elif not result.final_thai or result.final_thai.strip() == segment.source_text.strip():
                        logger.warning(
                            "[Worker] [Job %s] DeepSeek page recovery left %s untranslated; retaining it for review without cross-model fallback",
                            job_id,
                            segment.segment_id,
                        )

                    if assessment.passed:
                        result = TranslationResult(
                            segment_id=result.segment_id,
                            source_text=result.source_text,
                            draft_thai=result.draft_thai,
                            final_thai=result.final_thai,
                            model=result.model,
                            attempts=result.attempts,
                            qc_status="APPROVED",
                            issue_codes=result.issue_codes,
                        )
                        approved.append({"segment_id": segment.segment_id, "region_id": segment.region_id, "box": segment.box, "text": result.final_thai})
                        rolling_context.append({
                            "segment_id": segment.segment_id,
                            "source_text": segment.source_text,
                            "final_thai": result.final_thai,
                        })
                    else:
                        page_warnings = True
                        result = TranslationResult(
                            segment_id=result.segment_id,
                            source_text=result.source_text,
                            draft_thai=result.draft_thai,
                            final_thai=segment.source_text,
                            model=result.model,
                            attempts=result.attempts,
                            qc_status="NEEDS_REVIEW",
                            issue_codes=assessment.issue_codes,
                        )
                    final_page_results.append(result)

                if page_warnings:
                    warnings = True
                all_results.extend(final_page_results)
                render_candidates = associate_shifted_region_candidates(
                    RenderInstruction(
                        region_id=str(translation["region_id"]),
                        box=translation["box"],
                        text=translation["text"],
                    )
                    for translation in approved
                )
                render_instructions = deduplicate_render_instructions(render_candidates)
                build_render_instructions(render_instructions)
                if len(render_instructions) != len(approved):
                    logger.warning(
                        "[Worker] [Job %s] Page %d suppressed %d nested duplicate render regions",
                        job_id,
                        page["index"],
                        len(approved) - len(render_instructions),
                    )
                approved = [
                    {"box": instruction.box, "text": instruction.text}
                    for instruction in render_instructions
                ]
                page_render_jobs.append((page, approved))

            async def _render_page(page_dict: dict, approved_list: list):
                page_start = time.perf_counter()
                raw_bytes = page_dict["image_bytes"]
                render_start = time.perf_counter()
                if approved_list:
                    async with self.cpu_semaphore:
                        clean_bytes = await asyncio.to_thread(
                            self.inpainter.inpaint_image, raw_bytes, [item["box"] for item in approved_list]
                        )
                        final_bytes = await asyncio.to_thread(self.typesetter.typeset_image, clean_bytes, approved_list)
                else:
                    final_bytes = raw_bytes
                render_duration = time.perf_counter() - render_start
                return page_dict, approved_list, final_bytes, page_start, render_duration

            rendered_pages = await asyncio.gather(*[_render_page(pg, app) for pg, app in page_render_jobs])

            for completed_render_count, (page_dict, approved_list, final_bytes, page_start, render_duration) in enumerate(rendered_pages, start=1):
                current_job = await self._cancelled_job(job_id)
                if current_job:
                    logger.info("[Worker] Job %s cancelled before upload; discarding rendered pages", job_id)
                    return current_job
                upload_start = time.perf_counter()
                image_url = await self.r2_service.upload_image(
                    manga_slug=series_slug,
                    chapter_number=chapter_number,
                    page_index=page_dict["index"],
                    image_bytes=final_bytes,
                    content_type="image/jpeg",
                    run_id=run_id,
                )
                upload_duration = time.perf_counter() - upload_start
                staged_page = {
                    "page_index": page_dict["index"],
                    "image_url": image_url,
                    "raw_image_url": page_dict.get("raw_url"),
                }
                staged_pages.append(staged_page)
                page_duration = time.perf_counter() - page_start
                logger.info(
                    "[Worker] [Job %s] Page %d/%d processed in %.2fs (Render: %.2fs, Upload: %.2fs, Bubbles: %d) -> %s",
                    job_id, page_dict["index"], len(pages_data), page_duration, render_duration, upload_duration, len(approved_list), image_url
                )
                await self.job_repo.update(job_id, {
                    "progress_percent": int(60 + 35 * completed_render_count / max(len(pages_data), 1))
                })

            render_stage_duration = time.perf_counter() - stage_render_start
            logger.info(
                "[Worker] [Job %s] === STAGE 3/4 DONE in %.2fs (avg %.2fs/page) across %d pages ===",
                job_id, render_stage_duration, render_stage_duration / max(1, len(pages_data)), len(pages_data)
            )

            current_job = await self._cancelled_job(job_id)
            if current_job:
                logger.info("[Worker] Job %s cancelled before publishing", job_id)
                return current_job
            await self._record_artifacts(run_id, job_id, chapter.id, all_results, all_segments)
            if not publish:
                logger.info("[Worker] Job %s completed in SHADOW mode", job_id)
                return await self.job_repo.update(job_id, {
                    "status": "SHADOW_COMPLETED",
                    "progress_percent": 100,
                    "error_message": None,
                    "input_tokens": total_in_tokens,
                    "output_tokens": total_out_tokens,
                    "cost_estimate_usd": total_cost_usd,
                    "actual_model": actual_model or None,
                })
            # Always persist staged pages to DB with is_translated=True so reader can view what was produced.
            await self.page_repo.replace_for_chapter(chapter, staged_pages, is_translated=True)
            if warnings:
                logger.warning("[Worker] Job %s published with warnings — some dialogue regions need review", job_id)
                return await self.job_repo.update(job_id, {
                    "status": "COMPLETED_WITH_WARNINGS",
                    "progress_percent": 100,
                    "error_message": None,
                    "input_tokens": total_in_tokens,
                    "output_tokens": total_out_tokens,
                    "cost_estimate_usd": total_cost_usd,
                    "actual_model": actual_model or None,
                })
            final_status = "COMPLETED"
            total_job_duration = time.perf_counter() - job_start
            logger.info("[Worker] [Job %s] === JOB COMPLETED successfully in %.2fs (Status: %s) ===", job_id, total_job_duration, final_status)
            return await self.job_repo.update(job_id, {
                "status": final_status,
                "progress_percent": 100,
                "error_message": None,
                "input_tokens": total_in_tokens,
                "output_tokens": total_out_tokens,
                "cost_estimate_usd": total_cost_usd,
                "actual_model": actual_model or None,
            })
        except Exception as error:
            logger.exception("[Worker] Job %s FAILED with error: %s", job_id, error)
            await self.job_repo.update(job_id, {"status": "FAILED", "error_message": str(error)})
            raise

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Optional
import uuid

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
from src.pipeline.translator import AITranslatorEngine, TranslationResponseError
from src.infrastructure.ai.factory import get_ai_client
from src.pipeline.deepseek_batch_translator import DeepSeekBatchTranslator, group_pages_for_batching
from src.pipeline.typesetter import TypesetterEngine


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
)


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

            logger.info("[Worker] Job %s starting OCR across %d pages", job_id, len(pages_data))
            # OCR completes for every page before the first translation request, throttled via semaphore.
            async def _bounded_ocr(image_bytes: bytes, page_idx: int):
                async with self.cpu_semaphore:
                    return await self.ocr.detect_and_extract(image_bytes, page_index=page_idx)

            ocr_batches = await asyncio.gather(*(
                _bounded_ocr(page["image_bytes"], page["index"])
                for page in pages_data
            ))
            logger.info("[Worker] Job %s OCR completed across %d pages", job_id, len(pages_data))
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

            if provider in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat"):
                client = ai_client or get_ai_client(provider)
                batch_translator = DeepSeekBatchTranslator(client=client, provider=provider)
                ordered_page_segs = [segments_by_page[page["index"]] for page in pages_data]
                batches = group_pages_for_batching(ordered_page_segs)
                for page_batch in batches:
                    batch_res = await batch_translator.translate_page_batch(
                        page_batch,
                        glossary=tuple(glossary),
                        genre=str(profile.get("genre", "modern_cultivation")) if isinstance(profile, dict) else "modern_cultivation",
                    )
                    deepseek_translations.update(batch_res.translations)
                    total_in_tokens += batch_res.input_tokens
                    total_out_tokens += batch_res.output_tokens
                    total_cost_usd += batch_res.cost_usd
                    actual_model = batch_res.model

            for completed_pages, page in enumerate(pages_data, start=1):
                page_segments = segments_by_page[page["index"]]
                all_segments.update({segment.segment_id: segment for segment in page_segments})
                approved: list[dict[str, object]] = []
                page_results: list[TranslationResult] = []

                if provider in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat"):
                    for seg in page_segments:
                        translated_text = deepseek_translations.get(seg.segment_id, seg.source_text)
                        page_results.append(
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
                    missing_segs = list(page_segments)
                    if missing_segs:
                        request = TranslationBatchRequest(
                            segments=tuple(missing_segs),
                            profile=profile,
                            glossary=tuple(glossary),
                            context=tuple(rolling_context[-8:]),
                        )
                        try:
                            missing_res = await self.translator.translate_batch(request)
                            if isinstance(missing_res, Sequence):
                                page_results.extend(r for r in missing_res if isinstance(r, TranslationResult))
                        except Exception as batch_error:
                            logger.warning(
                                f"[Worker] translate_batch failed for missing segments on page {page['index']}: {batch_error}. Falling back..."
                            )

                    if len(page_results) < len(page_segments):
                        legacy_results = list(page_results)
                        existing_ids = {r.segment_id for r in page_results}
                        for segment in page_segments:
                            if segment.segment_id in existing_ids:
                                continue
                            translated = await self.translator.translate_text(
                                segment.source_text,
                                genre=str(profile.get("genre", "modern_cultivation")) if isinstance(profile, dict) else "modern_cultivation",
                            )
                            if not translated or translated == segment.source_text:
                                warnings = True
                            legacy_results.append(TranslationResult(
                                segment_id=segment.segment_id,
                                source_text=segment.source_text,
                                draft_thai=translated or segment.source_text,
                                final_thai=translated or segment.source_text,
                                model="fallback",
                                attempts=1,
                                qc_status="APPROVED" if translated else "NEEDS_REVIEW",
                                issue_codes=() if translated else ("EMPTY_TRANSLATION",),
                            ))
                        page_results = tuple(legacy_results)
                result_map = {
                    result.segment_id: result
                    for result in page_results
                    if isinstance(result, TranslationResult)
                }
                if set(result_map) != {segment.segment_id for segment in page_segments}:
                    warnings = True
                for segment in page_segments:
                    result = result_map.get(segment.segment_id)
                    if result is None:
                        thai_val = await self.translator.translate_text(
                            segment.source_text,
                            genre=str(profile.get("genre", "modern_cultivation")) if isinstance(profile, dict) else "modern_cultivation",
                        )
                        result = TranslationResult(
                            segment_id=segment.segment_id,
                            source_text=segment.source_text,
                            draft_thai=thai_val or segment.source_text,
                            final_thai=thai_val or segment.source_text,
                            model="single_fallback",
                            attempts=1,
                            qc_status="NEEDS_REVIEW",
                            issue_codes=("RESULT_COUNT_MISMATCH",),
                        )
                    assessment = self.quality_gate.evaluate(segment, result.final_thai, glossary)
                    if assessment.requires_semantic_review and not assessment.passed:
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
                            context=tuple(rolling_context[-8:]),
                        )
                        try:
                            reviewed = await self.translator.translate_batch(review_request)
                        except Exception:
                            reviewed = ()
                        if isinstance(reviewed, Sequence) and len(reviewed) == 1:
                            reviewer_result = reviewed[0]
                            result = TranslationResult(
                                segment_id=reviewer_result.segment_id,
                                source_text=segment.source_text,
                                draft_thai=result.draft_thai,
                                final_thai=reviewer_result.final_thai,
                                model=reviewer_result.model or result.model,
                                attempts=result.attempts + reviewer_result.attempts,
                                qc_status="PENDING",
                                issue_codes=assessment.issue_codes,
                            )
                            assessment = self.quality_gate.evaluate(segment, result.final_thai, glossary)
                        else:
                            assessment = type(assessment)(
                                passed=False,
                                issue_codes=tuple((*assessment.issue_codes, "INVALID_REVIEW_RESPONSE")),
                                requires_semantic_review=True,
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
                        approved.append({"box": segment.box, "text": result.final_thai})
                        rolling_context.append({
                            "segment_id": segment.segment_id,
                            "source_text": segment.source_text,
                            "final_thai": result.final_thai,
                        })
                    else:
                        warnings = True
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
                    all_results.append(result)

                raw_bytes = page["image_bytes"]
                if approved:
                    async with self.cpu_semaphore:
                        clean_bytes = await asyncio.to_thread(
                            self.inpainter.inpaint_image, raw_bytes, [item["box"] for item in approved]
                        )
                        final_bytes = await asyncio.to_thread(self.typesetter.typeset_image, clean_bytes, approved)
                else:
                    final_bytes = raw_bytes
                image_url = await self.r2_service.upload_image(
                    manga_slug=series_slug,
                    chapter_number=chapter_number,
                    page_index=page["index"],
                    image_bytes=final_bytes,
                    content_type="image/jpeg",
                    run_id=run_id,
                )
                staged_pages.append({
                    "page_index": page["index"],
                    "image_url": image_url,
                    "raw_image_url": page.get("raw_url"),
                })
                logger.info("[Worker] Job %s page %d/%d processed -> %s", job_id, completed_pages, len(pages_data), image_url)
                await self.job_repo.update(job_id, {
                    "progress_percent": int(55 + 35 * completed_pages / max(len(pages_data), 1))
                })

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
            await self.page_repo.replace_for_chapter(chapter, staged_pages, is_translated=True)
            final_status = "COMPLETED_WITH_WARNINGS" if warnings else "COMPLETED"
            logger.info("[Worker] Job %s finished publishing with status: %s", job_id, final_status)
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

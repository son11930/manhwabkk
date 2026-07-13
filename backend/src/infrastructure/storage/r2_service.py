import asyncio
import re
from typing import List, Dict, Any
from src.config import settings
from src.infrastructure.storage.r2_client import get_r2_client

class R2StorageService:
    """
    Service for managing manga images in Cloudflare R2 (S3-Compatible Storage).
    Implements mandatory browser caching headers and super-admin cleanup methods.
    """
    def __init__(self, client=None):
        self.client = client or get_r2_client()
        self.bucket = settings.R2_BUCKET_NAME
        self.public_url = settings.R2_DEV_URL

    @staticmethod
    def _safe_key_component(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", str(value)).strip("-")
        if not cleaned:
            raise ValueError("storage key component is invalid")
        return cleaned

    async def upload_image(
        self,
        manga_slug: str,
        chapter_number: str,
        page_index: int,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
        run_id: str | None = None,
    ) -> str:
        """
        Uploads a translated manga page to Cloudflare R2.
        Enforces immutable browser caching: Cache-Control: 'public, max-age=86400, immutable'
        Returns the public R2.dev URL for the Reader UI.
        """
        import time
        safe_slug = self._safe_key_component(manga_slug)
        safe_chapter = self._safe_key_component(chapter_number)
        safe_run_id = self._safe_key_component(run_id) if run_id else None
        key = f"{safe_slug}/{safe_chapter}/{page_index}.jpg"
        
        def _put():
            try:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=image_bytes,
                    ContentType=content_type,
                    CacheControl="public, max-age=86400, immutable"
                )
                print(f"[R2 Storage Success] Uploaded image to folder: {manga_slug}/{chapter_number}/ -> {key}")
                return f"{self.public_url}/{key}?t={int(time.time())}"
            except Exception as e:
                if settings.APP_ENV != "local":
                    raise
                # Local development fallback only. Production failures must abort the
                # staged run so the previously published reader URLs remain valid.
                print(f"[R2 Upload Warning] Could not upload to Cloudflare R2 ({e}). Saving to local folder: static/cache/{manga_slug}/{chapter_number}/")
                import os
                local_dir = os.path.join("static", "cache", safe_slug, safe_chapter)
                if safe_run_id:
                    local_dir = os.path.join(local_dir, safe_run_id)
                os.makedirs(local_dir, exist_ok=True)
                local_path = os.path.join(local_dir, f"{page_index}.jpg")
                with open(local_path, "wb") as f:
                    f.write(image_bytes)
                return f"http://localhost:8000/static/cache/{key}"
            
        return await asyncio.to_thread(_put)

    async def _delete_by_prefix(self, prefix: str) -> int:
        """Helper method to list and delete all objects matching a prefix."""
        def _delete():
            paginator = self.client.get_paginator("list_objects_v2")
            deleted_count = 0
            
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                if "Contents" not in page:
                    continue
                objects_to_delete = [{"Key": obj["Key"]} for obj in page["Contents"]]
                if objects_to_delete:
                    self.client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": objects_to_delete, "Quiet": True}
                    )
                    deleted_count += len(objects_to_delete)
            return deleted_count

        return await asyncio.to_thread(_delete)

    async def delete_chapter_images(self, manga_slug: str, chapter_number: str) -> int:
        """
        Protected Super Admin action: Deletes all images for a specific chapter.
        Returns the total number of deleted files.
        """
        prefix = f"{manga_slug}/{chapter_number}/"
        return await self._delete_by_prefix(prefix)

    async def delete_series_images(self, manga_slug: str) -> int:
        """
        Protected Super Admin action: Deletes all images for an entire manga series.
        Returns the total number of deleted files.
        """
        prefix = f"{manga_slug}/"
        return await self._delete_by_prefix(prefix)

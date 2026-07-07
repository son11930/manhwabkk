import asyncio
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

    async def upload_image(
        self,
        manga_slug: str,
        chapter_number: str,
        page_index: int,
        image_bytes: bytes,
        content_type: str = "image/jpeg"
    ) -> str:
        """
        Uploads a translated manga page to Cloudflare R2.
        Enforces immutable browser caching: Cache-Control: 'public, max-age=86400, immutable'
        Returns the public R2.dev URL for the Reader UI.
        """
        key = f"{manga_slug}/{chapter_number}/{page_index}.jpg"
        
        def _put():
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=image_bytes,
                ContentType=content_type,
                CacheControl="public, max-age=86400, immutable"
            )
            
        await asyncio.to_thread(_put)
        return f"{self.public_url}/{key}"

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

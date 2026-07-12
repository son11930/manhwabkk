import pytest
import boto3
from moto import mock_aws
from src.config import settings

# We will import R2StorageService once implemented
# from src.infrastructure.storage.r2_service import R2StorageService

@pytest.fixture
def mock_r2_bucket():
    """Sets up a mocked S3/R2 bucket using moto."""
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        )
        client.create_bucket(Bucket=settings.R2_BUCKET_NAME)
        yield client

@pytest.mark.asyncio
async def test_r2_upload_image_sets_immutable_cache(mock_r2_bucket):
    """
    Test that uploading an image sets the required immutable cache header:
    Cache-Control: public, max-age=86400, immutable
    and correct Content-Type: image/jpeg.
    """
    from src.infrastructure.storage.r2_service import R2StorageService
    service = R2StorageService()

    manga_slug = "solo-leveling"
    chapter_num = "chapter-1"
    page_index = 1
    image_data = b"fake-jpeg-image-bytes"

    # Action
    url = await service.upload_image(
        manga_slug=manga_slug,
        chapter_number=chapter_num,
        page_index=page_index,
        image_bytes=image_data,
        content_type="image/jpeg"
    )

    # Assert URL format matches blueprint:
    # manga-thai-storage / [manga-slug] / [chapter-number] / [page-index].jpg
    expected_key = f"{manga_slug}/{chapter_num}/{page_index}.jpg"
    expected_url = f"{settings.R2_DEV_URL}/{expected_key}"
    assert url.split('?')[0] == expected_url

    # Verify S3 Object metadata directly in mock bucket
    obj = mock_r2_bucket.get_object(Bucket=settings.R2_BUCKET_NAME, Key=expected_key)
    assert obj["CacheControl"] == "public, max-age=86400, immutable"
    assert obj["ContentType"] == "image/jpeg"
    assert obj["Body"].read() == image_data

@pytest.mark.asyncio
async def test_r2_delete_chapter_images(mock_r2_bucket):
    """
    Test that Super Admin delete chapter action only removes files belonging to that chapter.
    """
    from src.infrastructure.storage.r2_service import R2StorageService
    service = R2StorageService()

    manga_slug = "omniscient-reader"
    # Upload 2 pages for chapter-1 and 1 page for chapter-2
    await service.upload_image(manga_slug, "chapter-1", 1, b"page1")
    await service.upload_image(manga_slug, "chapter-1", 2, b"page2")
    await service.upload_image(manga_slug, "chapter-2", 1, b"page3")

    # Action: delete chapter-1
    deleted_count = await service.delete_chapter_images(manga_slug, "chapter-1")
    assert deleted_count == 2

    # Assert chapter-1 files are gone
    response = mock_r2_bucket.list_objects_v2(Bucket=settings.R2_BUCKET_NAME, Prefix=f"{manga_slug}/chapter-1/")
    assert "Contents" not in response

    # Assert chapter-2 file still exists
    response_ch2 = mock_r2_bucket.list_objects_v2(Bucket=settings.R2_BUCKET_NAME, Prefix=f"{manga_slug}/chapter-2/")
    assert len(response_ch2["Contents"]) == 1

@pytest.mark.asyncio
async def test_r2_delete_series_images(mock_r2_bucket):
    """
    Test that Super Admin delete series action removes all images for the entire manga series.
    """
    from src.infrastructure.storage.r2_service import R2StorageService
    service = R2StorageService()

    await service.upload_image("series-to-delete", "ch-1", 1, b"data1")
    await service.upload_image("series-to-delete", "ch-2", 1, b"data2")
    await service.upload_image("keep-series", "ch-1", 1, b"data3")

    # Action: delete series-to-delete
    deleted_count = await service.delete_series_images("series-to-delete")
    assert deleted_count == 2

    # Assert series-to-delete is empty
    resp_deleted = mock_r2_bucket.list_objects_v2(Bucket=settings.R2_BUCKET_NAME, Prefix="series-to-delete/")
    assert "Contents" not in resp_deleted

    # Assert keep-series still exists
    resp_keep = mock_r2_bucket.list_objects_v2(Bucket=settings.R2_BUCKET_NAME, Prefix="keep-series/")
    assert len(resp_keep["Contents"]) == 1

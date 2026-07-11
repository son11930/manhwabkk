import boto3
from botocore.config import Config
from src.config import settings

def get_r2_client():
    """
    Returns a configured boto3 S3 client for Cloudflare R2.
    During local testing / moto mocks, custom endpoint_url is omitted to allow local interception.
    """
    config = Config(
        signature_version="s3v4",
        retries={"max_attempts": 3, "mode": "standard"},
    )
    
    client_kwargs = {
        "service_name": "s3",
        "region_name": "us-east-1",  # R2 S3 API requires auto or us-east-1
        "aws_access_key_id": settings.R2_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.R2_SECRET_ACCESS_KEY,
        "config": config,
    }
    
    import os
    # Use real R2 endpoint if not running in pytest mock mode
    if "PYTEST_CURRENT_TEST" not in os.environ and not settings.R2_ACCOUNT_ID.startswith("12345678"):
        client_kwargs["endpoint_url"] = settings.r2_endpoint_url
        
    return boto3.client(**client_kwargs)

"""AWS S3 storage implementation."""

import os
import asyncio
from typing import Optional, List, Dict, AsyncIterator, Union
from pathlib import Path
import aioboto3
import boto3
from botocore.exceptions import ClientError

from .storage_interface import CloudStorageInterface


class S3Storage(CloudStorageInterface):
    """AWS S3 storage implementation."""

    def __init__(self, config: Dict):
        """Initialize S3 storage with configuration.
        
        Args:
            config: Configuration with access_key, secret_key, region, etc.
        """
        super().__init__(config)
        self._session = None

    async def initialize(self) -> None:
        """Initialize the S3 client."""
        # Set up AWS credentials from config
        aws_config = {
            'region_name': self.config.get('region', 'us-east-1')
        }
        
        if 'access_key' in self.config:
            aws_config['aws_access_key_id'] = os.path.expandvars(self.config['access_key'])
        if 'secret_key' in self.config:
            aws_config['aws_secret_access_key'] = os.path.expandvars(self.config['secret_key'])
        
        self._session = aioboto3.Session(**aws_config)
        self._client = await self._session.client('s3').__aenter__()

    async def download_file(
        self, 
        bucket: str, 
        key: str, 
        local_path: Union[str, Path],
        progress_callback: Optional[callable] = None
    ) -> Path:
        """Download a file from S3."""
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            # Get object size first
            response = await self._client.head_object(Bucket=bucket, Key=key)
            total_size = response['ContentLength']
            downloaded = 0

            # Download with progress
            response = await self._client.get_object(Bucket=bucket, Key=key)
            
            with open(local_path, 'wb') as f:
                async for chunk in response['Body'].iter_chunks(chunk_size=1024*1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    progress_callback(len(chunk))
        else:
            await self._client.download_file(bucket, key, str(local_path))

        return local_path

    async def upload_file(
        self, 
        local_path: Union[str, Path], 
        bucket: str, 
        key: str,
        progress_callback: Optional[callable] = None
    ) -> str:
        """Upload a file to S3."""
        local_path = Path(local_path)
        
        if progress_callback:
            # S3 upload with progress callback
            file_size = local_path.stat().st_size
            
            def upload_callback(bytes_amount):
                progress_callback(bytes_amount)
            
            await self._client.upload_file(
                str(local_path), 
                bucket, 
                key,
                Callback=upload_callback
            )
        else:
            await self._client.upload_file(str(local_path), bucket, key)
        
        return f"s3://{bucket}/{key}"

    async def download_directory(
        self, 
        bucket: str, 
        prefix: str, 
        local_dir: Union[str, Path],
        progress_callback: Optional[callable] = None
    ) -> Path:
        """Download a directory from S3."""
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)

        # List all objects with the prefix
        objects = await self.list_objects(bucket, prefix)
        
        # Download each object
        tasks = []
        for obj in objects:
            key = obj['name']
            relative_path = key[len(prefix):].lstrip('/')
            if relative_path:  # Skip the prefix itself
                local_file = local_dir / relative_path
                tasks.append(self.download_file(bucket, key, local_file, progress_callback))
        
        await asyncio.gather(*tasks)
        return local_dir

    async def upload_directory(
        self, 
        local_dir: Union[str, Path], 
        bucket: str, 
        prefix: str,
        progress_callback: Optional[callable] = None
    ) -> List[str]:
        """Upload a directory to S3."""
        local_dir = Path(local_dir)
        uploaded_urls = []
        
        tasks = []
        for file_path in local_dir.rglob('*'):
            if file_path.is_file():
                relative_path = file_path.relative_to(local_dir)
                key = f"{prefix}/{relative_path}".replace('//', '/')
                task = self.upload_file(file_path, bucket, key, progress_callback)
                tasks.append(task)
        
        uploaded_urls = await asyncio.gather(*tasks)
        return uploaded_urls

    async def list_objects(
        self, 
        bucket: str, 
        prefix: Optional[str] = None,
        max_results: Optional[int] = None
    ) -> List[Dict[str, any]]:
        """List objects in an S3 bucket."""
        objects = []
        
        paginator = self._client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(
            Bucket=bucket,
            Prefix=prefix or '',
            PaginationConfig={'MaxItems': max_results} if max_results else {}
        )
        
        async for page in page_iterator:
            if 'Contents' in page:
                for obj in page['Contents']:
                    objects.append({
                        'name': obj['Key'],
                        'size': obj['Size'],
                        'updated': obj['LastModified'],
                        'etag': obj['ETag'].strip('"'),
                        'storage_class': obj.get('StorageClass', 'STANDARD')
                    })
        
        return objects

    async def delete_object(self, bucket: str, key: str) -> None:
        """Delete an object from S3."""
        await self._client.delete_object(Bucket=bucket, Key=key)

    async def exists(self, bucket: str, key: str) -> bool:
        """Check if an object exists in S3."""
        try:
            await self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise

    async def get_object_metadata(self, bucket: str, key: str) -> Dict[str, any]:
        """Get metadata for an S3 object."""
        response = await self._client.head_object(Bucket=bucket, Key=key)
        
        return {
            'name': key,
            'size': response['ContentLength'],
            'updated': response['LastModified'],
            'etag': response['ETag'].strip('"'),
            'content_type': response.get('ContentType', ''),
            'metadata': response.get('Metadata', {})
        }

    async def stream_download(
        self, 
        bucket: str, 
        key: str,
        chunk_size: int = 8192
    ) -> AsyncIterator[bytes]:
        """Stream download an S3 object."""
        response = await self._client.get_object(Bucket=bucket, Key=key)
        
        async for chunk in response['Body'].iter_chunks(chunk_size=chunk_size):
            yield chunk

    async def close(self) -> None:
        """Close the S3 client."""
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
        self._session = None

    def parse_url(self, url: str) -> tuple[str, str]:
        """Parse an S3 URL into bucket and key."""
        if not url.startswith('s3://'):
            raise ValueError(f"Invalid S3 URL: {url}")
        
        parts = url[5:].split('/', 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ''
        
        return bucket, key
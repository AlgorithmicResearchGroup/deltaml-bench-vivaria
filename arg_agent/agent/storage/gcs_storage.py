"""Google Cloud Storage implementation."""

import os
import asyncio
from typing import Optional, List, Dict, AsyncIterator, Union
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import aiofiles
from google.cloud import storage
from google.oauth2 import service_account
import json

from .storage_interface import CloudStorageInterface


class GCSStorage(CloudStorageInterface):
    """Google Cloud Storage implementation."""

    def __init__(self, config: Dict):
        """Initialize GCS storage with configuration.
        
        Args:
            config: Configuration with credentials_path, project_id, etc.
        """
        super().__init__(config)
        self._executor = ThreadPoolExecutor(max_workers=10)

    async def initialize(self) -> None:
        """Initialize the GCS client."""
        def _create_client():
            credentials = None
            if 'credentials_path' in self.config:
                credentials_path = os.path.expandvars(self.config['credentials_path'])
                if os.path.exists(credentials_path):
                    credentials = service_account.Credentials.from_service_account_file(
                        credentials_path
                    )
            
            project_id = self.config.get('project_id')
            return storage.Client(credentials=credentials, project=project_id)

        loop = asyncio.get_event_loop()
        self._client = await loop.run_in_executor(self._executor, _create_client)

    async def download_file(
        self, 
        bucket: str, 
        key: str, 
        local_path: Union[str, Path],
        progress_callback: Optional[callable] = None
    ) -> Path:
        """Download a file from GCS."""
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        def _download():
            bucket_obj = self._client.bucket(bucket)
            blob = bucket_obj.blob(key)
            
            if progress_callback:
                # For progress tracking, we need to download in chunks
                with open(local_path, 'wb') as f:
                    blob.chunk_size = 1024 * 1024  # 1MB chunks
                    for chunk in blob.download_as_bytes(raw_download=True):
                        f.write(chunk)
                        progress_callback(len(chunk))
            else:
                blob.download_to_filename(str(local_path))
            
            return local_path

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _download)

    async def upload_file(
        self, 
        local_path: Union[str, Path], 
        bucket: str, 
        key: str,
        progress_callback: Optional[callable] = None
    ) -> str:
        """Upload a file to GCS."""
        local_path = Path(local_path)
        
        def _upload():
            bucket_obj = self._client.bucket(bucket)
            blob = bucket_obj.blob(key)
            
            if progress_callback:
                # For progress tracking, upload in chunks
                with open(local_path, 'rb') as f:
                    blob.chunk_size = 1024 * 1024  # 1MB chunks
                    blob.upload_from_file(f, rewind=True)
                    # Note: GCS Python client doesn't have built-in progress callbacks
                    # This is a simplified version
            else:
                blob.upload_from_filename(str(local_path))
            
            return f"gs://{bucket}/{key}"

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _upload)

    async def download_directory(
        self, 
        bucket: str, 
        prefix: str, 
        local_dir: Union[str, Path],
        progress_callback: Optional[callable] = None
    ) -> Path:
        """Download a directory from GCS."""
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
        """Upload a directory to GCS."""
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
        """List objects in a GCS bucket."""
        def _list():
            bucket_obj = self._client.bucket(bucket)
            blobs = bucket_obj.list_blobs(prefix=prefix, max_results=max_results)
            
            objects = []
            for blob in blobs:
                objects.append({
                    'name': blob.name,
                    'size': blob.size,
                    'updated': blob.updated,
                    'etag': blob.etag,
                    'content_type': blob.content_type
                })
            return objects

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _list)

    async def delete_object(self, bucket: str, key: str) -> None:
        """Delete an object from GCS."""
        def _delete():
            bucket_obj = self._client.bucket(bucket)
            blob = bucket_obj.blob(key)
            blob.delete()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, _delete)

    async def exists(self, bucket: str, key: str) -> bool:
        """Check if an object exists in GCS."""
        def _exists():
            bucket_obj = self._client.bucket(bucket)
            blob = bucket_obj.blob(key)
            return blob.exists()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _exists)

    async def get_object_metadata(self, bucket: str, key: str) -> Dict[str, any]:
        """Get metadata for a GCS object."""
        def _get_metadata():
            bucket_obj = self._client.bucket(bucket)
            blob = bucket_obj.blob(key)
            blob.reload()  # Fetch metadata
            
            return {
                'name': blob.name,
                'size': blob.size,
                'updated': blob.updated,
                'etag': blob.etag,
                'content_type': blob.content_type,
                'metadata': blob.metadata
            }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _get_metadata)

    async def stream_download(
        self, 
        bucket: str, 
        key: str,
        chunk_size: int = 8192
    ) -> AsyncIterator[bytes]:
        """Stream download a GCS object."""
        def _get_blob():
            bucket_obj = self._client.bucket(bucket)
            return bucket_obj.blob(key)

        loop = asyncio.get_event_loop()
        blob = await loop.run_in_executor(self._executor, _get_blob)
        
        # Download to a temporary file and stream from it
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        
        await loop.run_in_executor(
            self._executor, 
            lambda: blob.download_to_filename(tmp_path)
        )
        
        try:
            async with aiofiles.open(tmp_path, 'rb') as f:
                while True:
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        finally:
            os.unlink(tmp_path)

    async def close(self) -> None:
        """Close the GCS client."""
        self._executor.shutdown(wait=True)
        self._client = None

    def parse_url(self, url: str) -> tuple[str, str]:
        """Parse a GCS URL into bucket and key."""
        if not url.startswith('gs://'):
            raise ValueError(f"Invalid GCS URL: {url}")
        
        parts = url[5:].split('/', 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ''
        
        return bucket, key
"""Upload agent files to S3-compatible storage or local fallback"""
import os
import sys
import time
import threading
import hashlib
from pathlib import Path
import json

class MinioUploader:
    """Upload agent files to storage (S3-compatible or local)"""
    
    def __init__(self, run_id, working_dir="/tmp"):
        self.run_id = run_id
        self.working_dir = Path(working_dir) / f"worker_{run_id}_1"
        self.bucket_name = "agent-files"
        self.running = False
        self.thread = None
        self.uploaded_files = {}  # path -> (size, mtime, etag)
        
        # Try to use unified storage if available
        self.storage = None
        try:
            # Check if we're in the web context where unified storage is available
            from web.unified_storage import storage as unified_storage
            self.storage = unified_storage
            print(f"[MinioUploader] Using unified storage")
        except ImportError:
            # Fallback to local storage
            print(f"[MinioUploader] Using local storage fallback")
            self.local_storage_dir = Path("/tmp/agent_uploads") / run_id
            self.local_storage_dir.mkdir(parents=True, exist_ok=True)
    
    def _ensure_bucket(self):
        """Ensure storage is ready"""
        # No-op for unified storage or local fallback
        pass
    
    def start(self):
        """Start the uploader thread"""
        self.running = True
        self.thread = threading.Thread(target=self._upload_loop, daemon=True)
        self.thread.start()
        print(f"[MinioUploader] Started for run {self.run_id}")
    
    def stop(self):
        """Stop the uploader thread"""
        self.running = False
        if self.thread:
            self.thread.join()
        print(f"[MinioUploader] Stopped for run {self.run_id}")
    
    def _upload_loop(self):
        """Main loop to check and upload new/modified files"""
        while self.running:
            try:
                if self.working_dir.exists():
                    for file_path in self.working_dir.rglob('*'):
                        if file_path.is_file():
                            self._check_and_upload(file_path)
            except Exception as e:
                print(f"[MinioUploader] Error in upload loop: {e}")
            
            # Wait before next check
            time.sleep(10)
    
    def _check_and_upload(self, file_path):
        """Check if file needs upload and upload it"""
        try:
            # Get file stats
            stat = file_path.stat()
            size = stat.st_size
            mtime = stat.st_mtime
            
            # Check if file has changed
            rel_path = file_path.relative_to(self.working_dir)
            if str(rel_path) in self.uploaded_files:
                prev_size, prev_mtime, _ = self.uploaded_files[str(rel_path)]
                if size == prev_size and mtime == prev_mtime:
                    return  # File hasn't changed
            
            # Upload file
            object_name = f"{self.run_id}/{rel_path}"
            
            if self.storage:
                # Use unified storage
                with open(file_path, 'rb') as f:
                    content = f.read()
                success = self.storage.put_file(object_name, content)
                if success:
                    etag = hashlib.md5(content).hexdigest()
                    self.uploaded_files[str(rel_path)] = (size, mtime, etag)
                    print(f"[MinioUploader] Uploaded: {rel_path}")
            else:
                # Use local storage
                dest_path = self.local_storage_dir / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Copy file
                import shutil
                shutil.copy2(file_path, dest_path)
                
                # Calculate etag
                with open(file_path, 'rb') as f:
                    etag = hashlib.md5(f.read()).hexdigest()
                
                self.uploaded_files[str(rel_path)] = (size, mtime, etag)
                print(f"[MinioUploader] Copied to local storage: {rel_path}")
                
        except Exception as e:
            print(f"[MinioUploader] Error uploading {file_path}: {e}")
    
    def upload_directory(self, local_dir):
        """Upload entire directory"""
        local_path = Path(local_dir)
        if not local_path.exists():
            return
        
        for file_path in local_path.rglob('*'):
            if file_path.is_file():
                self._check_and_upload(file_path)
    
    def get_file_url(self, file_path):
        """Get URL for accessing uploaded file"""
        object_name = f"{self.run_id}/{file_path}"
        
        if self.storage and hasattr(self.storage, 'get_presigned_url'):
            # Try to get presigned URL
            url = self.storage.get_presigned_url(object_name)
            if url:
                return url
        
        # Fallback to local path
        if self.storage:
            return f"/api/storage/{object_name}"
        else:
            return f"file://{self.local_storage_dir}/{file_path}"
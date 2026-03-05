"""GPU allocation and management for parallel node execution."""

import asyncio
import os
from typing import Dict, List, Optional, Set, Tuple
from contextlib import asynccontextmanager
import torch
import subprocess
import json

from agent.utils.general import logger


class GPUAllocator:
    """Manages GPU allocation for parallel node execution"""
    
    def __init__(self):
        self.allocated_gpus: Dict[str, int] = {}  # node_id -> gpu_id
        self.gpu_locks: Dict[int, asyncio.Lock] = {}
        self.available_gpus: Set[int] = set()
        self.gpu_memory: Dict[int, Dict[str, float]] = {}
        self._initialized = False
        
    async def initialize(self):
        """Initialize GPU availability and create locks"""
        if self._initialized:
            return
            
        self.available_gpus = await self._detect_available_gpus()
        
        # Create locks for each GPU
        for gpu_id in self.available_gpus:
            self.gpu_locks[gpu_id] = asyncio.Lock()
            
        # Get initial memory stats
        await self._update_gpu_memory_stats()
        
        self._initialized = True
        logger.info(f"GPU Allocator initialized with {len(self.available_gpus)} GPUs: {list(self.available_gpus)}")
    
    async def _detect_available_gpus(self) -> Set[int]:
        """Detect available GPUs using multiple methods"""
        gpus = set()
        
        # Method 1: Check CUDA_VISIBLE_DEVICES
        cuda_devices = os.environ.get('CUDA_VISIBLE_DEVICES', '')
        if cuda_devices:
            try:
                gpus.update(int(d.strip()) for d in cuda_devices.split(',') if d.strip())
            except ValueError:
                pass
        
        # Method 2: Use PyTorch
        try:
            if torch.cuda.is_available():
                device_count = torch.cuda.device_count()
                gpus.update(range(device_count))
        except Exception as e:
            logger.warning(f"PyTorch GPU detection failed: {e}")
        
        # Method 3: Use nvidia-smi
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=index', '--format=csv,noheader'],
                capture_output=True, text=True, check=True
            )
            if result.returncode == 0:
                gpu_indices = [int(line.strip()) for line in result.stdout.strip().split('\n') if line.strip()]
                gpus.update(gpu_indices)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        
        return gpus if gpus else {0}  # Default to GPU 0 if none detected
    
    async def _update_gpu_memory_stats(self):
        """Update GPU memory statistics"""
        for gpu_id in self.available_gpus:
            try:
                # Use nvidia-smi to get memory stats
                result = subprocess.run(
                    ['nvidia-smi', '--id', str(gpu_id), '--query-gpu=memory.used,memory.total,memory.free',
                     '--format=csv,noheader,nounits'],
                    capture_output=True, text=True, check=True
                )
                if result.returncode == 0:
                    used, total, free = map(float, result.stdout.strip().split(', '))
                    self.gpu_memory[gpu_id] = {
                        'used_mb': used,
                        'total_mb': total,
                        'free_mb': free,
                        'utilization': (used / total) * 100
                    }
            except Exception:
                # Fallback: use PyTorch if available
                try:
                    if torch.cuda.is_available() and gpu_id < torch.cuda.device_count():
                        props = torch.cuda.get_device_properties(gpu_id)
                        allocated = torch.cuda.memory_allocated(gpu_id) / 1024**2  # MB
                        total = props.total_memory / 1024**2  # MB
                        self.gpu_memory[gpu_id] = {
                            'used_mb': allocated,
                            'total_mb': total,
                            'free_mb': total - allocated,
                            'utilization': (allocated / total) * 100
                        }
                except Exception:
                    pass
    
    async def get_least_loaded_gpu(self, min_free_memory_mb: float = 1000) -> Optional[int]:
        """Get the GPU with the most free memory"""
        await self._update_gpu_memory_stats()
        
        best_gpu = None
        max_free_memory = 0
        
        for gpu_id in self.available_gpus:
            if gpu_id not in self.allocated_gpus.values():  # Not currently allocated
                memory_info = self.gpu_memory.get(gpu_id, {})
                free_memory = memory_info.get('free_mb', 0)
                
                if free_memory >= min_free_memory_mb and free_memory > max_free_memory:
                    max_free_memory = free_memory
                    best_gpu = gpu_id
        
        return best_gpu
    
    @asynccontextmanager
    async def allocate_gpu_for_node(self, node_id: str, preferred_gpu: Optional[int] = None):
        """Context manager to allocate a GPU for a specific node"""
        if not self._initialized:
            await self.initialize()
        
        allocated_gpu = None
        
        try:
            # Try to get preferred GPU or find least loaded
            if preferred_gpu is not None and preferred_gpu in self.available_gpus:
                if preferred_gpu not in self.allocated_gpus.values():
                    allocated_gpu = preferred_gpu
            
            if allocated_gpu is None:
                allocated_gpu = await self.get_least_loaded_gpu()
            
            if allocated_gpu is None:
                # Fallback: use round-robin on available GPUs
                for gpu_id in self.available_gpus:
                    if gpu_id not in self.allocated_gpus.values():
                        allocated_gpu = gpu_id
                        break
            
            if allocated_gpu is not None:
                # Allocate the GPU
                async with self.gpu_locks[allocated_gpu]:
                    self.allocated_gpus[node_id] = allocated_gpu
                    logger.info(f"Allocated GPU {allocated_gpu} to node {node_id[:8]}")
                    
                    # Set CUDA_VISIBLE_DEVICES for this context
                    old_cuda_devices = os.environ.get('CUDA_VISIBLE_DEVICES', '')
                    os.environ['CUDA_VISIBLE_DEVICES'] = str(allocated_gpu)
                    
                    yield allocated_gpu
                    
                    # Restore original CUDA_VISIBLE_DEVICES
                    if old_cuda_devices:
                        os.environ['CUDA_VISIBLE_DEVICES'] = old_cuda_devices
                    else:
                        os.environ.pop('CUDA_VISIBLE_DEVICES', None)
            else:
                # No GPU available, yield None (CPU mode)
                logger.warning(f"No GPU available for node {node_id[:8]}, using CPU")
                yield None
                
        finally:
            # Clean up allocation
            if node_id in self.allocated_gpus:
                freed_gpu = self.allocated_gpus.pop(node_id)
                logger.info(f"Released GPU {freed_gpu} from node {node_id[:8]}")
    
    def get_allocation_status(self) -> Dict[str, any]:
        """Get current GPU allocation status"""
        return {
            'available_gpus': list(self.available_gpus),
            'allocated': dict(self.allocated_gpus),
            'gpu_memory': self.gpu_memory,
            'free_gpus': [gpu for gpu in self.available_gpus if gpu not in self.allocated_gpus.values()]
        }
    
    async def wait_for_gpu(self, timeout: float = 300) -> Optional[int]:
        """Wait for a GPU to become available"""
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            gpu = await self.get_least_loaded_gpu()
            if gpu is not None:
                return gpu
            
            # Wait a bit before checking again
            await asyncio.sleep(5)
        
        return None


# Global GPU allocator instance
gpu_allocator = GPUAllocator()
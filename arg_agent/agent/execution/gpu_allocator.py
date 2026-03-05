"""
GPU allocation and management for parallel execution.
"""

import re
from typing import Optional, Dict, Set, List
import logging

logger = logging.getLogger(__name__)


class GPUAllocator:
    """Manages GPU allocation for parallel node execution"""
    
    def __init__(self, available_gpus: Optional[List[int]] = None):
        """
        Initialize GPU allocator.
        
        Args:
            available_gpus: List of available GPU IDs. If None, will auto-detect.
        """
        self._allocations: Dict[str, int] = {}  # node_id -> gpu_id
        self._available_gpus: Set[int] = set()
        self._gpu_usage: Dict[int, str] = {}  # gpu_id -> node_id
        
        if available_gpus is not None:
            self._available_gpus = set(available_gpus)
        else:
            self._detect_available_gpus()
    
    def _detect_available_gpus(self) -> None:
        """Auto-detect available GPUs"""
        try:
            import torch
            if torch.cuda.is_available():
                gpu_count = torch.cuda.device_count()
                self._available_gpus = set(range(gpu_count))
                logger.info(f"Detected {gpu_count} available GPUs")
            else:
                logger.info("No CUDA GPUs detected")
        except ImportError:
            logger.warning("PyTorch not available for GPU detection")
        except Exception as e:
            logger.warning(f"Error detecting GPUs: {e}")
    
    def allocate(self, node_id: str) -> Optional[int]:
        """
        Allocate a GPU to a node.
        
        Args:
            node_id: ID of the node requesting GPU
            
        Returns:
            GPU ID if allocated, None if no GPUs available
        """
        # Check if already allocated
        if node_id in self._allocations:
            return self._allocations[node_id]
        
        # Find available GPU
        for gpu_id in self._available_gpus:
            if gpu_id not in self._gpu_usage:
                # Allocate this GPU
                self._allocations[node_id] = gpu_id
                self._gpu_usage[gpu_id] = node_id
                logger.info(f"Allocated GPU {gpu_id} to node {node_id[:8]}")
                return gpu_id
        
        logger.warning(f"No available GPUs for node {node_id[:8]}")
        return None
    
    def release(self, node_id: str) -> None:
        """
        Release GPU allocation for a node.
        
        Args:
            node_id: ID of the node releasing GPU
        """
        if node_id in self._allocations:
            gpu_id = self._allocations[node_id]
            del self._allocations[node_id]
            del self._gpu_usage[gpu_id]
            logger.info(f"Released GPU {gpu_id} from node {node_id[:8]}")
    
    def get_allocation(self, node_id: str) -> Optional[int]:
        """Get current GPU allocation for a node"""
        return self._allocations.get(node_id)
    
    def inject_device_selection(self, code: str, gpu_id: int) -> str:
        """
        Inject GPU device selection into code.
        
        Args:
            code: Python code to modify
            gpu_id: GPU ID to use
            
        Returns:
            Modified code with GPU device selection
        """
        # Check if code already has device selection
        if re.search(r'cuda:\d+|\.to\(.*device.*\)|device\s*=', code):
            logger.debug("Code already contains device selection")
            return code
        
        # Prepare device selection code
        device_code = f"""
# Auto-injected GPU device selection
import torch
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '{gpu_id}'
torch.cuda.set_device({gpu_id})
device = torch.device('cuda:{gpu_id}' if torch.cuda.is_available() else 'cpu')
print(f"Using device: {{device}} (GPU {gpu_id} allocated)")

# Original code follows:
"""
        
        # Inject at the beginning
        modified_code = device_code + code
        
        # Also try to inject .to(device) calls for common patterns
        patterns = [
            # Model creation patterns
            (r'(\w+)\s*=\s*(\w+Model|nn\.\w+|torch\.nn\.\w+)\(', r'\1 = \2('),
            # After model creation, add .to(device)
            (r'(model|net|network)\s*=\s*([^=]+)(?=\n)', r'\1 = \2.to(device)'),
        ]
        
        for pattern, replacement in patterns:
            if re.search(pattern, modified_code) and '.to(device)' not in modified_code:
                modified_code = re.sub(pattern, replacement, modified_code)
        
        return modified_code
    
    def get_stats(self) -> Dict[str, any]:
        """Get allocation statistics"""
        return {
            'total_gpus': len(self._available_gpus),
            'allocated_gpus': len(self._gpu_usage),
            'free_gpus': len(self._available_gpus) - len(self._gpu_usage),
            'allocations': dict(self._allocations)
        }
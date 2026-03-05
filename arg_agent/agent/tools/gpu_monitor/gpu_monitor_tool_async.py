"""GPU monitoring tool for tracking GPU utilization and memory with CPU fallback."""

import asyncio
import json
import time
import psutil
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from agent.tools.base_tool import AsyncTool
from agent.utils.general import logger


class GPUMonitorTool(AsyncTool):
    """
    Monitor GPU utilization and memory usage for ML workloads.
    Gracefully falls back to CPU monitoring when GPU is not available.
    """
    
    def __init__(self):
        super().__init__(
            name="gpu_monitor",
            description=(
                "Monitor GPU/CPU utilization and memory for ML workloads. "
                "Returns current usage stats and can track usage over time. "
                "Automatically falls back to CPU monitoring when GPU is unavailable."
            ),
            examples=[
                {"input": {"action": "check"}, "output": "Current GPU/CPU usage stats"},
                {"input": {"action": "start_tracking", "interval": 1}, "output": "Started tracking"},
                {"input": {"action": "stop_tracking"}, "output": "Tracking summary"}
            ]
        )
        self.tracking = False
        self.tracking_data = []
        self.tracking_task = None
        self.has_gpu = self._check_gpu_availability()
        
    def _check_gpu_availability(self) -> bool:
        """Check if GPU monitoring is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            try:
                import tensorflow as tf
                return len(tf.config.list_physical_devices('GPU')) > 0
            except ImportError:
                return False
    
    async def _check_gpu_torch(self) -> Dict[str, Any]:
        """Check GPU stats using PyTorch."""
        try:
            import torch
            if not torch.cuda.is_available():
                return {"error": "No CUDA GPU available"}
            
            device_count = torch.cuda.device_count()
            stats = {
                "backend": "pytorch",
                "device_count": device_count,
                "devices": []
            }
            
            for i in range(device_count):
                device_props = torch.cuda.get_device_properties(i)
                memory_allocated = torch.cuda.memory_allocated(i) / 1024**3  # GB
                memory_reserved = torch.cuda.memory_reserved(i) / 1024**3    # GB
                memory_total = device_props.total_memory / 1024**3          # GB
                
                device_info = {
                    "device_id": i,
                    "name": device_props.name,
                    "compute_capability": f"{device_props.major}.{device_props.minor}",
                    "memory": {
                        "total_gb": round(memory_total, 2),
                        "allocated_gb": round(memory_allocated, 2),
                        "reserved_gb": round(memory_reserved, 2),
                        "free_gb": round(memory_total - memory_allocated, 2),
                        "utilization_percent": round((memory_allocated / memory_total) * 100, 1)
                    }
                }
                
                # Try to get utilization (not always available)
                try:
                    import pynvml
                    pynvml.nvmlInit()
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    device_info["utilization"] = {
                        "gpu_percent": util.gpu,
                        "memory_percent": util.memory
                    }
                    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    device_info["temperature_c"] = temp
                except:
                    pass
                
                stats["devices"].append(device_info)
            
            return stats
            
        except Exception as e:
            return {"error": f"PyTorch GPU check failed: {str(e)}"}
    
    async def _check_gpu_tensorflow(self) -> Dict[str, Any]:
        """Check GPU stats using TensorFlow."""
        try:
            import tensorflow as tf
            gpus = tf.config.list_physical_devices('GPU')
            
            if not gpus:
                return {"error": "No TensorFlow GPU available"}
            
            stats = {
                "backend": "tensorflow", 
                "device_count": len(gpus),
                "devices": []
            }
            
            for i, gpu in enumerate(gpus):
                device_info = {
                    "device_id": i,
                    "name": gpu.name,
                    "device_type": gpu.device_type
                }
                
                # TF doesn't provide easy memory stats, try nvidia-smi
                try:
                    import subprocess
                    result = subprocess.run(
                        ['nvidia-smi', '--query-gpu=memory.used,memory.total,utilization.gpu', 
                         '--format=csv,noheader,nounits', '-i', str(i)],
                        capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        used, total, util = result.stdout.strip().split(', ')
                        device_info["memory"] = {
                            "used_mb": int(used),
                            "total_mb": int(total),
                            "utilization_percent": round((int(used) / int(total)) * 100, 1)
                        }
                        device_info["utilization"] = {"gpu_percent": int(util)}
                except:
                    pass
                
                stats["devices"].append(device_info)
            
            return stats
            
        except Exception as e:
            return {"error": f"TensorFlow GPU check failed: {str(e)}"}
    
    async def _check_cpu_stats(self) -> Dict[str, Any]:
        """Check CPU and system memory stats as fallback."""
        try:
            # CPU stats
            cpu_percent = psutil.cpu_percent(interval=0.1, percpu=True)
            cpu_freq = psutil.cpu_freq()
            
            # Memory stats
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Process-specific stats
            process = psutil.Process()
            process_memory = process.memory_info()
            
            stats = {
                "backend": "cpu",
                "device_type": "CPU",
                "cpu": {
                    "count": psutil.cpu_count(logical=False),
                    "logical_count": psutil.cpu_count(logical=True),
                    "percent": round(sum(cpu_percent) / len(cpu_percent), 1),
                    "per_core_percent": [round(p, 1) for p in cpu_percent],
                    "frequency_mhz": round(cpu_freq.current, 1) if cpu_freq else None
                },
                "memory": {
                    "total_gb": round(memory.total / 1024**3, 2),
                    "available_gb": round(memory.available / 1024**3, 2),
                    "used_gb": round(memory.used / 1024**3, 2),
                    "percent": round(memory.percent, 1)
                },
                "swap": {
                    "total_gb": round(swap.total / 1024**3, 2),
                    "used_gb": round(swap.used / 1024**3, 2),
                    "percent": round(swap.percent, 1)
                },
                "process": {
                    "memory_gb": round(process_memory.rss / 1024**3, 2),
                    "cpu_percent": round(process.cpu_percent(), 1)
                }
            }
            
            return stats
            
        except Exception as e:
            return {"error": f"CPU monitoring failed: {str(e)}"}
    
    async def _check_current_stats(self) -> Dict[str, Any]:
        """Check current GPU or CPU stats."""
        timestamp = datetime.now().isoformat()
        
        # Try GPU first
        if self.has_gpu:
            # Try PyTorch
            stats = await self._check_gpu_torch()
            if "error" not in stats:
                stats["timestamp"] = timestamp
                return stats
            
            # Try TensorFlow
            stats = await self._check_gpu_tensorflow()
            if "error" not in stats:
                stats["timestamp"] = timestamp
                return stats
        
        # Fall back to CPU
        stats = await self._check_cpu_stats()
        stats["timestamp"] = timestamp
        stats["note"] = "GPU not available, showing CPU stats"
        return stats
    
    async def _tracking_loop(self, interval: float):
        """Background tracking loop."""
        while self.tracking:
            stats = await self._check_current_stats()
            self.tracking_data.append(stats)
            await asyncio.sleep(interval)
    
    def _summarize_tracking_data(self) -> Dict[str, Any]:
        """Summarize collected tracking data."""
        if not self.tracking_data:
            return {"error": "No tracking data collected"}
        
        summary = {
            "duration_seconds": len(self.tracking_data) * (self.tracking_data[1]["timestamp"] if len(self.tracking_data) > 1 else 1),
            "samples": len(self.tracking_data),
            "backend": self.tracking_data[0].get("backend", "unknown")
        }
        
        if summary["backend"] == "cpu":
            # CPU summary
            cpu_percents = [d["cpu"]["percent"] for d in self.tracking_data if "cpu" in d]
            memory_percents = [d["memory"]["percent"] for d in self.tracking_data if "memory" in d]
            
            summary["cpu"] = {
                "avg_percent": round(sum(cpu_percents) / len(cpu_percents), 1) if cpu_percents else 0,
                "max_percent": round(max(cpu_percents), 1) if cpu_percents else 0,
                "min_percent": round(min(cpu_percents), 1) if cpu_percents else 0
            }
            summary["memory"] = {
                "avg_percent": round(sum(memory_percents) / len(memory_percents), 1) if memory_percents else 0,
                "max_percent": round(max(memory_percents), 1) if memory_percents else 0,
                "min_percent": round(min(memory_percents), 1) if memory_percents else 0
            }
        else:
            # GPU summary
            gpu_data = []
            memory_data = []
            
            for sample in self.tracking_data:
                if "devices" in sample:
                    for device in sample["devices"]:
                        if "utilization" in device and "gpu_percent" in device["utilization"]:
                            gpu_data.append(device["utilization"]["gpu_percent"])
                        if "memory" in device and "utilization_percent" in device["memory"]:
                            memory_data.append(device["memory"]["utilization_percent"])
            
            if gpu_data:
                summary["gpu_utilization"] = {
                    "avg_percent": round(sum(gpu_data) / len(gpu_data), 1),
                    "max_percent": round(max(gpu_data), 1),
                    "min_percent": round(min(gpu_data), 1)
                }
            
            if memory_data:
                summary["gpu_memory"] = {
                    "avg_percent": round(sum(memory_data) / len(memory_data), 1),
                    "max_percent": round(max(memory_data), 1),
                    "min_percent": round(min(memory_data), 1)
                }
        
        # Check for potential issues
        summary["warnings"] = []
        
        if summary["backend"] == "cpu":
            if summary.get("memory", {}).get("max_percent", 0) > 90:
                summary["warnings"].append("High memory usage detected (>90%)")
            if summary.get("cpu", {}).get("max_percent", 0) > 90:
                summary["warnings"].append("High CPU usage detected (>90%)")
        else:
            if summary.get("gpu_memory", {}).get("max_percent", 0) > 90:
                summary["warnings"].append("High GPU memory usage detected (>90%)")
            if summary.get("gpu_utilization", {}).get("avg_percent", 0) < 50:
                summary["warnings"].append("Low GPU utilization - consider increasing batch size")
        
        return summary
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute GPU monitoring action."""
        action = input_data.get("action", "check")
        
        if action == "check":
            # One-time check
            stats = await self._check_current_stats()
            
            # Add recommendations based on stats
            if stats.get("backend") == "pytorch" and "devices" in stats:
                for device in stats["devices"]:
                    memory = device.get("memory", {})
                    if memory.get("utilization_percent", 0) > 90:
                        stats["recommendation"] = "GPU memory nearly full - reduce batch size"
                    elif memory.get("utilization_percent", 0) < 30:
                        stats["recommendation"] = "GPU memory underutilized - consider increasing batch size"
            
            return {"output": stats}
        
        elif action == "start_tracking":
            if self.tracking:
                return {"output": {"status": "Already tracking"}}
            
            interval = input_data.get("interval", 1.0)
            self.tracking = True
            self.tracking_data = []
            self.tracking_task = asyncio.create_task(self._tracking_loop(interval))
            
            return {"output": {
                "status": "Started tracking",
                "interval": interval,
                "backend": "GPU" if self.has_gpu else "CPU"
            }}
        
        elif action == "stop_tracking":
            if not self.tracking:
                return {"output": {"status": "Not currently tracking"}}
            
            self.tracking = False
            if self.tracking_task:
                self.tracking_task.cancel()
                try:
                    await self.tracking_task
                except asyncio.CancelledError:
                    pass
            
            summary = self._summarize_tracking_data()
            self.tracking_data = []  # Clear data
            
            return {"output": {
                "status": "Stopped tracking",
                "summary": summary
            }}
        
        elif action == "get_tracking_data":
            if not self.tracking_data:
                return {"output": {"error": "No tracking data available"}}
            
            return {"output": {
                "data": self.tracking_data[-10:],  # Last 10 samples
                "total_samples": len(self.tracking_data)
            }}
        
        else:
            return {"output": {"error": f"Unknown action: {action}"}}
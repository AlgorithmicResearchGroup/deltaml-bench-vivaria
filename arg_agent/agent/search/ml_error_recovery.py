"""ML-specific error recovery strategies."""

import re
from typing import Dict, Optional, Tuple, List
from agent.core.solution_tree import SolutionNode


class MLErrorRecovery:
    """Provides ML-specific error recovery strategies."""
    
    @staticmethod
    def check_experiment_tracking(code: str) -> Dict[str, any]:
        """Check if experiment tracking is properly integrated."""
        has_wandb = "import wandb" in code or "from wandb" in code
        has_init = "wandb.init" in code or "wandb_run" in code
        has_logging = "wandb.log" in code or "safe_wandb_log" in code
        
        if not has_wandb or not has_init or not has_logging:
            return {
                "strategy": "add_experiment_tracking",
                "suggestions": [
                    "Missing W&B experiment tracking - this is MANDATORY for ML training",
                    "Use experiment_tracker(action='check_setup') first",
                    "Then use experiment_tracker(action='generate_tracking_code') to create tracked script",
                    "This prevents lost experiments and ensures reproducibility"
                ],
                "code_modifications": [{
                    "pattern": "import torch",
                    "replacement": "import torch\nimport wandb  # REQUIRED for experiment tracking"
                }],
                "priority": "critical"
            }
        return None
    
    @staticmethod
    def get_recovery_strategy(error_type: str, node: SolutionNode) -> Dict[str, any]:
        """Get recovery strategy for a specific ML error type."""
        
        error_text = (node.exec_error or node.exec_stderr or "").lower()
        stdout_text = (node.exec_stdout or "").lower()
        
        strategies = {
            "cuda_oom": MLErrorRecovery._handle_cuda_oom,
            "shape_mismatch": MLErrorRecovery._handle_shape_mismatch,
            "nan_loss": MLErrorRecovery._handle_nan_loss,
            "inf_loss": MLErrorRecovery._handle_inf_loss,
            "memory_killed": MLErrorRecovery._handle_memory_killed,
            "dimension_error": MLErrorRecovery._handle_dimension_error,
            "dtype_mismatch": MLErrorRecovery._handle_dtype_mismatch,
            "device_mismatch": MLErrorRecovery._handle_device_mismatch,
            "empty_data": MLErrorRecovery._handle_empty_data,
            "missing_column": MLErrorRecovery._handle_missing_column,
        }
        
        # First check if experiment tracking is missing (critical for ML)
        tracking_check = MLErrorRecovery.check_experiment_tracking(node.code)
        if tracking_check:
            return tracking_check
        
        if error_type in strategies:
            return strategies[error_type](error_text, stdout_text, node)
        
        return {
            "strategy": "generic",
            "suggestions": ["Review the error message and fix the issue"],
            "code_modifications": []
        }
    
    @staticmethod
    def _handle_cuda_oom(error_text: str, stdout_text: str, node: SolutionNode) -> Dict:
        """Handle CUDA out of memory errors."""
        suggestions = []
        code_mods = []
        
        # Add GPU monitoring suggestion
        suggestions.append("Monitor GPU memory usage with gpu_monitor tool before training")
        code_mods.append({
            "pattern": "(model\\.train\\(\\))",
            "replacement": "# Check GPU memory before training\\n    gpu_stats = gpu_monitor(action='check')\\n    print(f\"GPU Memory: {gpu_stats}%\")\\n    \\1"
        })
        
        # Try to extract current batch size
        batch_match = re.search(r'batch[_\s]*size[:\s]*(\d+)', node.code)
        if batch_match:
            current_batch = int(batch_match.group(1))
            new_batch = max(1, current_batch // 2)
            suggestions.append(f"Reduce batch size from {current_batch} to {new_batch}")
            code_mods.append({
                "pattern": f"batch_size\\s*=\\s*{current_batch}",
                "replacement": f"batch_size = {new_batch}"
            })
        else:
            suggestions.append("Add explicit batch_size parameter and set it to a small value (e.g., 8 or 16)")
            code_mods.append({
                "pattern": "DataLoader\\(([^)]+)\\)",
                "replacement": "DataLoader(\\1, batch_size=8)"
            })
        
        # Additional strategies
        suggestions.extend([
            "Enable gradient checkpointing if using transformers",
            "Use mixed precision training (torch.cuda.amp)",
            "Clear cache with torch.cuda.empty_cache() periodically",
            "Consider using gradient accumulation",
            "Track GPU memory usage during training with gpu_monitor(action='start_tracking')"
        ])
        
        code_mods.extend([
            {
                "pattern": "model\\.train\\(\\)",
                "replacement": "model.train()\\n    torch.cuda.empty_cache()"
            },
            {
                "pattern": "optimizer\\.zero_grad\\(\\)",
                "replacement": "optimizer.zero_grad()\\n        torch.cuda.empty_cache()"
            }
        ])
        
        return {
            "strategy": "reduce_memory",
            "suggestions": suggestions,
            "code_modifications": code_mods,
            "priority": "high"
        }
    
    @staticmethod
    def _handle_shape_mismatch(error_text: str, stdout_text: str, node: SolutionNode) -> Dict:
        """Handle tensor shape mismatch errors."""
        suggestions = []
        code_mods = []
        
        # Extract shape information
        shape_match = re.search(r'size \\[(\\d+)[^\\]]*\\][^\\[]*\\[(\\d+)', error_text)
        if shape_match:
            shape1, shape2 = shape_match.groups()
            suggestions.append(f"Detected shape mismatch: {shape1} vs {shape2}")
        
        # Common fixes
        suggestions.extend([
            "Add print statements to debug tensor shapes throughout the forward pass",
            "Check if you need to flatten or reshape tensors between layers",
            "Verify that your model's input/output dimensions match the data",
            "Consider using adaptive pooling layers for variable input sizes"
        ])
        
        code_mods.extend([
            {
                "pattern": "(x = self\\.\\w+\\(x\\))",
                "replacement": "\\1\\n        print(f'Shape after layer: {x.shape}')"
            },
            {
                "pattern": "return x",
                "replacement": "x = x.view(x.size(0), -1)  # Flatten if needed\\n        return x"
            }
        ])
        
        return {
            "strategy": "fix_shapes",
            "suggestions": suggestions,
            "code_modifications": code_mods,
            "priority": "high"
        }
    
    @staticmethod
    def _handle_nan_loss(error_text: str, stdout_text: str, node: SolutionNode) -> Dict:
        """Handle NaN loss during training."""
        suggestions = []
        code_mods = []
        
        # Check if it's early or late NaN
        if "epoch 0" in error_text or "step 0" in error_text:
            suggestions.extend([
                "NaN in early training - likely due to high learning rate or improper initialization",
                "Reduce learning rate by factor of 10",
                "Check data normalization - ensure no division by zero",
                "Initialize weights with smaller values"
            ])
            code_mods.append({
                "pattern": "lr\\s*=\\s*([0-9.e-]+)",
                "replacement": lambda m: f"lr = {float(m.group(1)) * 0.1}"
            })
        else:
            suggestions.extend([
                "NaN during training - gradient explosion likely",
                "Add gradient clipping",
                "Reduce learning rate",
                "Check for numerical instability in loss computation"
            ])
            code_mods.append({
                "pattern": "optimizer\\.step\\(\\)",
                "replacement": "torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)\\n        optimizer.step()"
            })
        
        # Add stability checks
        code_mods.extend([
            {
                "pattern": "loss\\.backward\\(\\)",
                "replacement": "if not torch.isnan(loss):\\n            loss.backward()\\n        else:\\n            print(f'NaN loss detected at step {step}')"
            },
            {
                "pattern": "eps=([0-9.e-]+)",
                "replacement": "eps=1e-8"  # Increase epsilon for stability
            }
        ])
        
        return {
            "strategy": "stabilize_training",
            "suggestions": suggestions,
            "code_modifications": code_mods,
            "priority": "high"
        }
    
    @staticmethod
    def _handle_inf_loss(error_text: str, stdout_text: str, node: SolutionNode) -> Dict:
        """Handle infinite loss values."""
        return {
            "strategy": "prevent_overflow",
            "suggestions": [
                "Use torch.clamp() to limit values in loss computation",
                "Switch to a more numerically stable loss function",
                "Add small epsilon to denominators",
                "Use log-sum-exp trick for numerical stability"
            ],
            "code_modifications": [
                {
                    "pattern": "torch\\.log\\(([^)]+)\\)",
                    "replacement": "torch.log(\\1 + 1e-8)"
                },
                {
                    "pattern": "loss = ",
                    "replacement": "loss = torch.clamp("
                }
            ],
            "priority": "high"
        }
    
    @staticmethod
    def _handle_memory_killed(error_text: str, stdout_text: str, node: SolutionNode) -> Dict:
        """Handle process killed due to memory (OOM killer)."""
        return {
            "strategy": "reduce_dataset_memory",
            "suggestions": [
                "Process data in smaller chunks",
                "Use data generators instead of loading all data into memory",
                "Reduce dataset size for initial experiments",
                "Enable data loading with num_workers=0 to reduce memory overhead",
                "Consider using memory-mapped files for large datasets"
            ],
            "code_modifications": [
                {
                    "pattern": "num_workers=\\d+",
                    "replacement": "num_workers=0"
                },
                {
                    "pattern": "\\.to\\(device\\)",
                    "replacement": ".to(device, non_blocking=True)"
                }
            ],
            "priority": "high"
        }
    
    @staticmethod
    def _handle_dimension_error(error_text: str, stdout_text: str, node: SolutionNode) -> Dict:
        """Handle dimension out of range errors."""
        return {
            "strategy": "fix_dimensions",
            "suggestions": [
                "Check tensor dimensions before operations",
                "Use .squeeze() or .unsqueeze() to adjust dimensions",
                "Verify that dimension indices are within bounds",
                "Print tensor shapes to debug dimension issues"
            ],
            "code_modifications": [
                {
                    "pattern": "\\.mean\\((\\d+)\\)",
                    "replacement": lambda m: f".mean({m.group(1)}, keepdim=True)"
                },
                {
                    "pattern": "dim=(\\d+)",
                    "replacement": lambda m: f"dim={m.group(1)} if x.dim() > {m.group(1)} else -1"
                }
            ],
            "priority": "medium"
        }
    
    @staticmethod
    def _handle_dtype_mismatch(error_text: str, stdout_text: str, node: SolutionNode) -> Dict:
        """Handle data type mismatches."""
        suggestions = []
        code_mods = []
        
        if "float" in error_text and "long" in error_text:
            suggestions.append("Cast labels to long for classification: labels.long()")
            code_mods.append({
                "pattern": "loss\\(([^,]+),\\s*([^)]+)\\)",
                "replacement": "loss(\\1, \\2.long())"
            })
        elif "double" in error_text:
            suggestions.append("Ensure all tensors use float32: tensor.float()")
            code_mods.append({
                "pattern": "\\.double\\(\\)",
                "replacement": ".float()"
            })
        
        suggestions.extend([
            "Set default dtype: torch.set_default_dtype(torch.float32)",
            "Check data loading dtype consistency",
            "Ensure model and data have matching precision"
        ])
        
        return {
            "strategy": "fix_dtypes",
            "suggestions": suggestions,
            "code_modifications": code_mods,
            "priority": "medium"
        }
    
    @staticmethod
    def _handle_device_mismatch(error_text: str, stdout_text: str, node: SolutionNode) -> Dict:
        """Handle device mismatch between tensors."""
        return {
            "strategy": "fix_devices",
            "suggestions": [
                "Ensure all tensors are on the same device",
                "Move model and data to device explicitly",
                "Use .to(device) consistently throughout the code"
            ],
            "code_modifications": [
                {
                    "pattern": "model\\(([^)]+)\\)",
                    "replacement": "model(\\1.to(device))"
                },
                {
                    "pattern": "^(\\s*)(\\w+)\\s*=\\s*torch\\.",
                    "replacement": "\\1\\2 = torch."
                }
            ],
            "priority": "high"
        }
    
    @staticmethod
    def _handle_empty_data(error_text: str, stdout_text: str, node: SolutionNode) -> Dict:
        """Handle empty dataset or tensor errors."""
        return {
            "strategy": "validate_data",
            "suggestions": [
                "Check if dataset is being loaded correctly",
                "Verify file paths and data preprocessing",
                "Add assertions to check data size",
                "Print dataset length after loading"
            ],
            "code_modifications": [
                {
                    "pattern": "(train_loader = DataLoader\\([^)]+\\))",
                    "replacement": "\\1\\nprint(f'Train dataset size: {len(train_loader.dataset)}')"
                },
                {
                    "pattern": "for .+ in .+loader:",
                    "replacement": "if len(loader) == 0:\\n        raise ValueError('DataLoader is empty')\\n    for batch in loader:"
                }
            ],
            "priority": "high"
        }
    
    @staticmethod
    def _handle_missing_column(error_text: str, stdout_text: str, node: SolutionNode) -> Dict:
        """Handle missing column in dataset."""
        suggestions = []
        code_mods = []
        
        # Try to extract column name
        key_match = re.search(r"keyerror[:\\s]*['\"]([^'\"]+)", error_text)
        if key_match:
            col_name = key_match.group(1)
            suggestions.append(f"Column '{col_name}' not found in dataset")
            suggestions.append("Check available columns with df.columns or dataset.feature_names")
            code_mods.append({
                "pattern": f"\\['{col_name}'\\]",
                "replacement": f".get('{col_name}', default_value)"  # Safer access
            })
        
        suggestions.extend([
            "Print column names to verify they match your code",
            "Check for case sensitivity in column names",
            "Ensure data file has headers if using pandas"
        ])
        
        return {
            "strategy": "fix_columns",
            "suggestions": suggestions,
            "code_modifications": code_mods,
            "priority": "high"
        }
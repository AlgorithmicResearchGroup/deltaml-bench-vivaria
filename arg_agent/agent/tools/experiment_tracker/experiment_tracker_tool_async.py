"""Weights & Biases experiment tracking tool with robust error handling."""

import os
import asyncio
import json
import re
from typing import Dict, Any, Optional, List
from datetime import datetime
import tempfile
from pathlib import Path

from agent.tools.base_tool import AsyncTool
from agent.utils.general import logger


class ExperimentTrackerTool(AsyncTool):
    """
    Weights & Biases integration for experiment tracking.
    Handles API keys, prevents blocking, and ensures consistent usage.
    """
    
    def __init__(self):
        super().__init__(
            name="experiment_tracker",
            description=(
                "Integrate Weights & Biases tracking into ML training scripts. "
                "Automatically handles API keys, prevents blocking, and ensures all experiments are tracked. "
                "Use 'check_setup' first, then 'generate_tracking_code' for every ML script."
            ),
            examples=[
                {"input": {"action": "check_setup"}, "output": "W&B setup status and instructions"},
                {"input": {"action": "generate_tracking_code", "config": {...}}, "output": "Complete tracking code"},
                {"input": {"action": "validate_script", "code": "..."}, "output": "Validation results"},
            ]
        )
        self.template_cache = {}
        self._check_wandb_setup()
        
    def _check_wandb_setup(self):
        """Check if W&B is properly configured."""
        self.has_api_key = bool(os.environ.get("WANDB_API_KEY"))
        self.wandb_mode = "online" if self.has_api_key else "offline"
        
        # Set environment to prevent blocking
        os.environ["WANDB_SILENT"] = "true"
        os.environ["WANDB_DISABLE_CODE"] = "true"  # Don't upload code
        
        if not self.has_api_key:
            logger.warning("WANDB_API_KEY not found. Will use offline mode.")
    
    def _generate_safe_init_code(self, config: Dict[str, Any]) -> str:
        """Generate W&B initialization code that won't block."""
        project = config.get("project", "ml-agent-experiments")
        name = config.get("name", f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        tags = config.get("tags", [])
        notes = config.get("notes", "Automated experiment by ML agent")
        hyperparams = config.get("hyperparameters", {})
        
        init_code = f'''
# Weights & Biases Setup (Safe Mode)
import os
from datetime import datetime

# Try to import wandb, but make it optional
try:
    import wandb
    WANDB_AVAILABLE = True
except ImportError:
    WANDB_AVAILABLE = False
    wandb = None

# Prevent W&B from blocking on user input
os.environ["WANDB_SILENT"] = "true"
os.environ["WANDB_DISABLE_CODE"] = "true"

# Check for API key and set mode
if WANDB_AVAILABLE:
    wandb_mode = "online" if os.environ.get("WANDB_API_KEY") else "offline"
    if wandb_mode == "offline":
        print("⚠️ W&B running in offline mode. Run 'wandb sync' later to upload.")

    # Initialize W&B with error handling
    try:
        wandb_run = wandb.init(
        project="{project}",
        name="{name}",
        tags={tags},
        notes="{notes}",
        config={hyperparams},
        mode=wandb_mode,
        reinit=True,  # Allow multiple inits
        settings=wandb.Settings(
            silent=True,
            disable_code=True,
            _disable_stats=False  # Keep system metrics
        )
        )
        print(f"✅ W&B tracking initialized: {{wandb_run.name}}")
    except Exception as e:
        print(f"⚠️ W&B initialization failed: {{e}}. Continuing without tracking.")
        wandb_run = None
else:
    print("⚠️ W&B not available. Install with: pip install wandb")
    wandb_run = None

# Helper function for safe logging
def safe_wandb_log(metrics_dict):
    """Safely log metrics to W&B, ignore if not initialized."""
    if wandb_run is not None and WANDB_AVAILABLE:
        try:
            wandb.log(metrics_dict)
        except Exception as e:
            print(f"Warning: W&B logging failed: {{e}}")
'''
        return init_code
    
    def _generate_training_template(self, config: Dict[str, Any]) -> str:
        """Generate a complete training script template with W&B integration."""
        init_code = self._generate_safe_init_code(config)
        
        template = f'''{init_code}

# Training Configuration
config = wandb.config if wandb_run else {config.get("hyperparameters", {})}

# Model checkpoint helper
def save_checkpoint(model, optimizer, epoch, metrics, is_best=False):
    """Save model checkpoint with W&B artifact tracking."""
    checkpoint = {{
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'metrics': metrics,
        'config': dict(config)
    }}
    
    # Save locally
    checkpoint_path = f"checkpoint_epoch_{{epoch}}.pt"
    if is_best:
        checkpoint_path = "best_model.pt"
    torch.save(checkpoint, checkpoint_path)
    
    # REQUIRED: Upload to W&B if available (for ALL saved models, not just best)
    if wandb_run is not None:
        try:
            artifact_name = f"{{wandb_run.project}}-model-best" if is_best else f"{{wandb_run.project}}-model-epoch-{{epoch}}"
            artifact = wandb.Artifact(
                name=artifact_name,
                type="model",
                description=f"Model checkpoint with {{metrics}}"
            )
            artifact.add_file(checkpoint_path)
            wandb_run.log_artifact(artifact)
            print(f"✅ Model uploaded to W&B as artifact: {{artifact_name}}")
        except Exception as e:
            print(f"Warning: Failed to upload model artifact: {{e}}")

# Training loop with integrated logging
def train_epoch(model, train_loader, optimizer, epoch):
    model.train()
    total_loss = 0
    correct = 0
    total = 0
    
    for batch_idx, (data, target) in enumerate(train_loader):
        # Your training logic here
        optimizer.zero_grad()
        output = model(data)
        loss = criterion(output, target)
        loss.backward()
        optimizer.step()
        
        # Track metrics
        total_loss += loss.item()
        pred = output.argmax(dim=1)
        correct += pred.eq(target).sum().item()
        total += target.size(0)
        
        # Log batch metrics periodically
        if batch_idx % 10 == 0:
            safe_wandb_log({{
                "batch_loss": loss.item(),
                "batch_idx": batch_idx + epoch * len(train_loader)
            }})
    
    # Calculate epoch metrics
    epoch_metrics = {{
        "epoch": epoch,
        "train_loss": total_loss / len(train_loader),
        "train_acc": correct / total,
        "learning_rate": optimizer.param_groups[0]['lr']
    }}
    
    # Log epoch metrics
    safe_wandb_log(epoch_metrics)
    
    return epoch_metrics

# Validation with logging
def validate(model, val_loader, epoch):
    model.eval()
    val_loss = 0
    correct = 0
    total = 0
    
    with torch.no_grad():
        for data, target in val_loader:
            output = model(data)
            val_loss += criterion(output, target).item()
            pred = output.argmax(dim=1)
            correct += pred.eq(target).sum().item()
            total += target.size(0)
    
    val_metrics = {{
        "epoch": epoch,
        "val_loss": val_loss / len(val_loader),
        "val_acc": correct / total
    }}
    
    # Log validation metrics
    safe_wandb_log(val_metrics)
    
    return val_metrics

# Main training loop
best_val_acc = 0
patience_counter = 0
max_patience = {config.get("early_stopping_patience", 10)}

for epoch in range({config.get("epochs", 100)}):
    # Train
    train_metrics = train_epoch(model, train_loader, optimizer, epoch)
    
    # Validate
    val_metrics = validate(model, val_loader, epoch)
    
    print(f"Epoch {{epoch}}: Train Loss={{train_metrics['train_loss']:.4f}}, "
          f"Train Acc={{train_metrics['train_acc']:.4f}}, "
          f"Val Loss={{val_metrics['val_loss']:.4f}}, "
          f"Val Acc={{val_metrics['val_acc']:.4f}}")
    
    # Save checkpoint if best
    if val_metrics['val_acc'] > best_val_acc:
        best_val_acc = val_metrics['val_acc']
        save_checkpoint(model, optimizer, epoch, val_metrics, is_best=True)
        patience_counter = 0
    else:
        patience_counter += 1
    
    # Early stopping
    if patience_counter >= max_patience:
        print(f"Early stopping at epoch {{epoch}}")
        safe_wandb_log({{"early_stopped": True, "final_epoch": epoch}})
        break

# Final logging
if wandb_run is not None:
    wandb_run.summary["best_val_acc"] = best_val_acc
    wandb_run.finish()
    print("✅ W&B run completed successfully")
'''
        return template
    
    def _inject_tracking_into_code(self, code: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Inject W&B tracking into existing training code."""
        # Check if W&B is already imported
        has_wandb = "import wandb" in code or "from wandb" in code
        
        if has_wandb:
            return {"status": "already_tracked", "code": code}
        
        # Find training loop patterns
        loop_patterns = [
            r"for\s+epoch\s+in\s+range",
            r"while\s+epoch\s*<",
            r"for\s+\w+\s+in\s+epochs",
        ]
        
        has_training_loop = any(re.search(pattern, code, re.IGNORECASE) for pattern in loop_patterns)
        
        if not has_training_loop:
            return {"status": "no_training_loop", "code": code}
        
        # Inject initialization at the beginning
        init_code = self._generate_safe_init_code(config)
        
        # Find imports section
        import_match = re.search(r"(import\s+\w+|from\s+\w+\s+import)", code)
        if import_match:
            insert_pos = import_match.start()
            # Find the end of imports
            lines = code[:insert_pos].split('\n')
            import_end = len('\n'.join(lines))
            code = code[:import_end] + "\n" + init_code + "\n" + code[import_end:]
        else:
            # No imports found, add at beginning
            code = init_code + "\n\n" + code
        
        # Inject logging into training loops
        # This is simplified - in practice would need more sophisticated parsing
        code = self._add_logging_calls(code)
        
        return {"status": "tracking_injected", "code": code}
    
    def _add_logging_calls(self, code: str) -> str:
        """Add W&B logging calls to training code."""
        # Add safe_wandb_log after loss calculations
        patterns = [
            (r"(loss\s*=\s*[^\n]+)", r"\1\n        safe_wandb_log({'loss': loss.item() if hasattr(loss, 'item') else loss})"),
            (r"(accuracy\s*=\s*[^\n]+)", r"\1\n        safe_wandb_log({'accuracy': accuracy})"),
            (r"(train_loss\s*=\s*[^\n]+)", r"\1\n        safe_wandb_log({'train_loss': train_loss})"),
        ]
        
        for pattern, replacement in patterns:
            code = re.sub(pattern, replacement, code)
        
        return code
    
    def _validate_tracking_integration(self, code: str) -> Dict[str, Any]:
        """Validate that tracking is properly integrated."""
        issues = []
        
        # Check for W&B import
        if "import wandb" not in code:
            issues.append("Missing 'import wandb'")
        
        # Check for initialization
        if "wandb.init" not in code and "wandb_run" not in code:
            issues.append("Missing W&B initialization")
        
        # Check for logging
        if "wandb.log" not in code and "safe_wandb_log" not in code:
            issues.append("No W&B logging calls found")
        
        # Check for error handling
        if "try:" not in code or "except" not in code:
            issues.append("Missing error handling for W&B calls")
        
        # Check for offline mode handling
        if "WANDB_API_KEY" not in code and "wandb_mode" not in code:
            issues.append("No offline mode handling")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "recommendation": "Use generate_tracking_code to get a properly integrated template" if issues else "Tracking properly integrated"
        }
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute experiment tracking actions."""
        action = input_data.get("action", "check_setup")
        
        if action == "check_setup":
            # Check W&B setup and provide guidance
            return {"output": {
                "status": "ready" if self.has_api_key else "offline_mode",
                "has_api_key": self.has_api_key,
                "mode": self.wandb_mode,
                "instructions": (
                    "W&B is ready for online tracking." if self.has_api_key else
                    "W&B will run in offline mode. Experiments will be saved locally. "
                    "To enable online tracking, set WANDB_API_KEY environment variable."
                ),
                "next_step": "Use 'generate_tracking_code' action to create a tracked training script"
            }}
        
        elif action == "generate_tracking_code":
            # Generate complete training template with tracking
            config = input_data.get("config", {})
            template = self._generate_training_template(config)
            
            return {"output": {
                "code": template,
                "instructions": "Complete training template with W&B tracking. Fill in your model and data loading code.",
                "features": [
                    "Automatic online/offline mode detection",
                    "Error handling to prevent blocking",
                    "Checkpoint saving with artifacts",
                    "Early stopping support",
                    "System metrics tracking"
                ]
            }}
        
        elif action == "inject_tracking":
            # Add tracking to existing code
            code = input_data.get("code", "")
            config = input_data.get("config", {})
            
            result = self._inject_tracking_into_code(code, config)
            
            return {"output": result}
        
        elif action == "validate_script":
            # Validate that tracking is properly integrated
            code = input_data.get("code", "")
            validation = self._validate_tracking_integration(code)
            
            return {"output": validation}
        
        elif action == "generate_safe_log":
            # Generate safe logging code snippet
            metrics = input_data.get("metrics", ["loss", "accuracy"])
            
            log_code = "# Safe W&B logging\n"
            for metric in metrics:
                log_code += f'safe_wandb_log({{"{metric}": {metric}}})\n'
            
            return {"output": {"code": log_code}}
        
        elif action == "log_metrics":
            # Log metrics directly to a local JSON file (since W&B may not be initialized)
            metrics = input_data.get("metrics", {})
            code_snippet = input_data.get("code_snippet", "")
            
            # Create experiments directory if it doesn't exist
            exp_dir = Path("experiments")
            exp_dir.mkdir(exist_ok=True)
            
            # Create a log entry
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "metrics": metrics,
                "code_snippet": code_snippet[:500] if code_snippet else "",  # First 500 chars
                "wandb_mode": self.wandb_mode,
                "has_api_key": self.has_api_key
            }
            
            # Append to experiments log file
            log_file = exp_dir / "experiment_log.jsonl"
            try:
                with open(log_file, 'a') as f:
                    f.write(json.dumps(log_entry) + '\n')
                
                return {"output": {
                    "status": "logged",
                    "location": str(log_file),
                    "metrics": metrics,
                    "message": f"Metrics logged to {log_file}"
                }}
            except Exception as e:
                return {"output": {
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to log metrics"
                }}
        
        else:
            return {"output": {"error": f"Unknown action: {action}"}}
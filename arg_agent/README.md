# ARG Agent - Vivaria Integration

This directory contains a Vivaria-compatible wrapper for the Algorithmic Research Group (ARG) Agent system.

## Overview

The ARG Agent is a sophisticated ML research agent with:
- Advanced beam search and solution tree exploration
- Comprehensive tool system (Python, Bash, GPU monitoring, etc.)
- Memory management and context building
- Error analysis and recovery
- Reflection and monitoring capabilities
- Multi-LLM support (OpenAI, Anthropic, Google)

## Architecture

```
Vivaria Platform
    ↓ (pyhooks)
main.py (Vivaria wrapper)
    ↓
ARGAgentWorker (Extended AsyncWorker)
    ↓
Original ARG Agent Components:
- Solution Tree & Beam Search
- Tool Registry & Execution
- Memory Management
- Reflection & Monitoring
```

## Usage

### Basic Usage
```bash
viv run \
    --agent-path arg_agent \
    --task-family-path RE-Bench/ai_rd_triton_cumsum \
    --env-file-path secrets.env \
    ai_rd_triton_cumsum/main
```

### With Custom Settings
```bash
viv run \
    --agent-path arg_agent \
    --agent-settings-pack arg_reasoning \
    --max_tokens 5000000 \
    --task-family-path RE-Bench/ai_rd_fix_embedding \
    --env-file-path secrets.env \
    ai_rd_fix_embedding/main
```

## Settings Packs

- **arg_default**: Standard configuration with GPT-4o
- **arg_reasoning**: Uses o1 reasoning model for complex problems
- **arg_fast**: Quick mode with GPT-4o-mini
- **arg_comprehensive**: Full exploration with higher iteration limits

## Features

### ARG Agent Capabilities
- ✅ Advanced problem decomposition
- ✅ Parallel exploration strategies
- ✅ Sophisticated error recovery
- ✅ Memory-aware context management
- ✅ Multi-modal tool integration
- ✅ Reflection-based improvement

### Vivaria Integration
- ✅ Full pyhooks compliance
- ✅ Tool system mapping
- ✅ State management
- ✅ Usage tracking
- ✅ Error handling
- ✅ Multiple configuration options

## Tool Mapping

| ARG Agent Tool | Vivaria Tool | Description |
|----------------|--------------|-------------|
| PythonTool | python | Execute Python code |
| BashTool | bash | Run bash commands |
| SubmissionTool | submit | Submit solutions |
| ScoreTool | score | Get intermediate scores |

## Configuration

The agent can be configured via settings packs in `manifest.json`:

```json
{
    "model": "o3-mini",
    "max_iterations": 50,
    "context_window_tokens": 16000,
    "enable_reflection": true,
    "enable_monitoring": true
}
```

## Development

### Adding New Tools
1. Create tool in `tool_adapter.py`
2. Register in `ToolAdapter._setup_tools()`
3. Add definition in `get_tool_definitions()`

### Extending Agent Logic
1. Modify `ARGAgentWorker` in `main.py`
2. Override specific methods for custom behavior
3. Add new settings packs in `manifest.json`

## Troubleshooting

### Common Issues
- **Import errors**: Ensure ARG agent path is correct
- **Tool failures**: Check Vivaria tool compatibility
- **Memory issues**: Reduce context_window_tokens
- **Timeout**: Increase max_total_seconds parameter

### Debugging
- Check logs in Vivaria web interface
- Monitor agent state saves
- Use simplified solving fallback if needed

## Performance Tips

1. **For speed**: Use `arg_fast` settings pack
2. **For accuracy**: Use `arg_reasoning` with o1 model
3. **For exploration**: Use `arg_comprehensive` 
4. **For debugging**: Enable full monitoring and reflection

## Compatibility

- ✅ RE-Bench tasks
- ✅ Vivaria platform
- ✅ Multi-LLM providers
- ✅ GPU tasks
- ✅ Complex ML research problems

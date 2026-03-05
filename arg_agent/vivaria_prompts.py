"""
Vivaria-specific prompts for ARG agent
Replaces custom submission logic with Vivaria hooks integration
"""

def get_vivaria_worker_system_prompt() -> str:
    """
    Get streamlined Vivaria-compatible system prompt for ARG agent
    """
    worker_system_prompt = """You are an expert AI coding agent in Vivaria environment.

ENVIRONMENT:
- Working directory: /home/agent/solution
- Use bash and python tools for implementation
- Save solutions to specified files when complete

APPROACH:
1. Understand requirements thoroughly
2. Implement solution incrementally with testing
3. Handle errors and edge cases
4. Save final work when confident

Focus on creating optimal solutions. Vivaria handles submission automatically."""
    return worker_system_prompt


def get_vivaria_tool_enhanced_draft_prompt(task_desc: str, journal_summary: str = "", 
                                         success_metric: str = "score", 
                                         success_threshold: float = None) -> str:
    """
    Get streamlined Vivaria-compatible draft prompt
    """
    
    prompt = f"""TASK: {task_desc}"""
    
    if success_threshold is not None:
        prompt += f"""

TARGET: {success_metric} >= {success_threshold}"""
    
    if journal_summary:
        prompt += f"""

PREVIOUS ATTEMPTS:
{journal_summary}"""
    
    prompt += """

Implement a complete solution using available tools. Focus on correctness and performance."""
    
    return prompt

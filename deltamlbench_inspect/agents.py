from __future__ import annotations

from inspect_ai.agent import Agent, agent, react
from inspect_ai.tool import bash, python, text_editor, update_plan


def _common_tools():
    return [
        bash(timeout=1800),
        python(timeout=1800),
        text_editor(timeout=1800),
        update_plan(),
    ]


@agent(name="pwc_react")
def pwc_react() -> Agent:
    return react(
        prompt=(
            "You are solving a long-horizon ML code optimization task inside a sandbox. "
            "Read the task instructions carefully, inspect the repository and dataset artifacts in /home/agent, "
            "edit /home/agent/solution/solution.py, run experiments with the available tools, and submit only after "
            "you have a coherent final solution."
        ),
        tools=_common_tools(),
    )


@agent(name="modular_public_bridge")
def modular_public_bridge() -> Agent:
    return react(
        prompt=(
            "Work like a deliberate coding agent. Prefer inspecting files, testing assumptions, and iterating on "
            "solution.py. Keep a short plan, use tools frequently, and optimize for measured task score rather than "
            "premature submission."
        ),
        tools=_common_tools(),
    )


@agent(name="arg_agent_bridge")
def arg_agent_bridge() -> Agent:
    return react(
        prompt=(
            "Operate like a research-style coding agent. Explore multiple approaches when progress stalls, keep notes "
            "on what changed, and optimize the benchmark score through genuine training and evaluation work."
        ),
        tools=_common_tools(),
    )

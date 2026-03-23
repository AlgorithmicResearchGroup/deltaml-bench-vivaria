from __future__ import annotations

from inspect_ai.solver import Generate, TaskState, solver


@solver
def baseline_submit():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        del generate
        state.output.completion = "baseline"
        state.completed = True
        return state

    return solve

"""Project-owned prompt overrides for the ``write_todos`` middleware."""

from typing import Literal

from langchain.agents.middleware import TodoListMiddleware
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.utils.todolists import MAX_TODOLIST_SUMMARY_LENGTH, preserve_completed_summaries


class ExtendedTodo(BaseModel):
    content: str = Field(
        description=(
            "Natural, user-facing Chinese step description, preferably 15-50 Chinese characters and never more "
            "than 60 characters. Write one complete action sentence that explains what will be done, to what "
            "business or scientific object, and for what immediate goal. Include known domain information such "
            "as the calculation software, algorithm, input data, important parameters, target property, or expected "
            "deliverable when it helps the user understand the step. Do not invent details that are still unknown. "
            "Do not expose internal tool names, skill names, function names, implementation stages, or long file paths. "
            "Good: 检查晶体结构、赝势文件和SCF参数是否齐全 / "
            "提取总能量和收敛信息，判断计算结果是否可信. "
            "Bad: 准备输入文件 / 提交并运行计算 / 调用scnet_remote_shell_execute."
        )
    )
    status: Literal["pending", "in_progress", "completed", "skipped"]
    summary: str = Field(
        default="",
        max_length=MAX_TODOLIST_SUMMARY_LENGTH,
        description=(
            "Only for a genuinely completed step: one short Chinese sentence with its verified result "
            "and the next planned business objective, normally 30-60 characters. No heading or tool narration. "
            "Write for a non-specialist: say what is ready or established and what happens next in plain Chinese. "
            "Retain one or two verified task-specific details, such as the method and its meaning, "
            "prepared input categories, a traceable job identifier, or a key result; do not make every summary generic. "
            "Omit parameter codes, software class names, file inventories and raw status codes; "
            "keep only details needed to understand the result, find a deliverable or make a decision. "
            "Retain essential result values with units, uncertainty and limitations. "
            "Submitted does not mean running; a finished job does not prove a valid or converged result. "
            "For the final step, describe its delivered result without inventing a next step. "
            "Keep empty until completed. Preserve this summary in later full-plan updates. "
            "It belongs to this step; do not repeat it as ordinary assistant text."
        ),
    )


class ExtendedWriteTodosInput(BaseModel):
    todos: list[ExtendedTodo]


WRITE_TODOS_TOOL_DESCRIPTION = """Use this tool to create or update the complete task list for the current objective.

Each call replaces the entire todo list. Always submit the complete latest list.

Each todo `content` is rendered directly in the UI. Write it as one natural, complete Chinese action sentence,
preferably 15-50 Chinese characters and never more than 60 characters. It should tell the user what will be done,
which business or scientific object is involved, and the immediate goal. When already known, include useful domain
information such as the software, algorithm, input data, important parameters, target property, or expected
deliverable. Never invent details that have not been established.

Keep the plan at the level of meaningful workflow outcomes rather than individual tool calls. Do not expose internal
tool names, skill names, function names, implementation stages, or long file paths. Avoid empty generic wording such
as "准备输入文件" or "分析计算结果" when the available context can identify the actual inputs,
method, result, or validation goal.

Good: 检查晶体结构、赝势文件和SCF参数是否齐全
Good: 使用Quantum ESPRESSO完成SnO₂的SCF自洽场计算
Good: 提取总能量和收敛信息，判断计算结果是否可信
Bad:  准备输入文件
Bad:  提交并运行计算
Bad:  调用scnet_remote_shell_execute执行计算

Use these statuses:

- `pending`: Work has not started.
- `in_progress`: Work currently being performed.
- `completed`: Work has been fully completed.
- `skipped`: User explicitly chose to skip this step via an action card. Only use when instructed by the system.

For every unfinished plan, exactly one item must be `in_progress`; all other unfinished items must be `pending`.

Update the plan before starting a planned item and immediately after completing it. Preserve every completed item and never change, remove, or revert it. Remove unfinished items that are no longer required.

Never change an item directly from `pending` to `completed`. If it was never performed and is no longer needed, remove it. If it was accidentally completed early, first mark it `in_progress` in a separate call; after that call returns, output "<item content>已经执行完成" in the assistant text, then mark it `completed` in another call and continue the plan. This fallback does not authorize early work.

Never mark incomplete, failed, blocked, or unverified work as `completed`. Never call `write_todos` in parallel with another `write_todos` call or with a business operation.

Use this tool for complex or multi-step objectives, or whenever another system instruction requires a plan.
Write summaries for readers without domain training: name the concrete outcome and next business action in plain Chinese, not a log of technical settings. Omit routine parameter codes, class names, file inventories, paths and raw status codes; include identifiers only when needed to locate a deliverable or follow up. Explain any essential technical term briefly. Keep decision-relevant values with units, limitations and uncertainty. Do not replace details with empty claims like "处理完成" or "一切正常". Submission, execution ending and scientific result validation are different outcomes; never imply a later outcome has been verified.
Keep routine execution silent from the start of the task, including before this tool is first called and while reading instructions or preparing a plan. Do not add greetings, opening acknowledgements, phase preambles or narration between tools. In the same update that marks a genuinely finished step `completed`, fill that item's `summary` with one short sentence of verified result and next planned objective. Preserve completed summaries in every later update. Do not output step summaries as ordinary assistant text, narrate individual tools, or announce plan updates. Required decisions and blockers remain visible; after the final plan update, provide the overall delivery summary."""

WRITE_TODOS_SYSTEM_PROMPT = """## `write_todos`

Use `write_todos` to manage complex, multi-step, or explicitly requested plans. A workflow-specific instruction may require a plan even when the objective appears simple.

Preserve the existing plan and tool activity. Throughout routine execution, assistant prose must be empty, whether or not a plan or an `in_progress` item already exists. This includes before the first tool call, reading instructions before planning, creating/updating the plan, transitions between steps, and continuation. Do not add greetings, opening acknowledgements, phase preambles, ordinary tool-result commentary, or narration of plan updates. Do not create or reorder steps merely to satisfy this display rule.

A step's result-and-next-step sentence belongs only in that item's `summary` field, not in ordinary assistant text. Populate it in the same `write_todos` call that marks the step `completed`; a simultaneous activation of the next step does not transfer ownership of this summary. Use one short Chinese sentence, usually 30–60 characters and at most 120, without a heading, repeated step title, or tool list. Keep summaries empty on unfinished or skipped steps and preserve all completed summaries in later full-plan updates. Do not change step boundaries, required transitions, or completion criteria to produce summaries. Necessary user decisions, blockers, consequential assumption changes, required asynchronous notices, prescribed analysis/reports and the final delivery summary remain allowed; these exceptions do not permit routine progress narration.

### Plain-language step summaries

Plain language must not mean loss of useful information. Include one or two verified details that distinguish this step: the chosen method and what it does, prepared input categories, a queue/job identifier needed for tracking, or a key measured result. Explain their practical meaning instead of removing all technical terms. Do not repeat details already clear in the step title merely to fill space, and do not invent precision or validation to make a summary richer.

The reader need not understand scientific software. State what is now ready or known and the next planned action in everyday Chinese. Preserve the concrete task or object; avoid vague filler such as "处理完成". Do not copy parameter codes, implementation class names, file inventories, paths or raw status codes into the summary. Keep a technical term, identifier or filename only when it helps the user understand a result, make a decision or locate a deliverable; briefly explain essential jargon. Keep key result values with units and material limitations or uncertainty, even when simplifying the wording.

Only when supported by the actual results and plan:
- Files prepared: "已准备好金刚石的结构文件、计算参数和碳元素所需的计算数据，接下来提交到集群运行。"
- Submission accepted: "任务已提交到 agent2 队列，作业编号为 5231，接下来跟踪运行状态。" Use the actual returned queue and identifier, never copy these example values. Do not claim it is already running.
- Execution ended, results not yet checked: "作业 5231 已结束，接下来检查能量是否达到设定的稳定标准，并提取最终能量。" Use the actual identifier. Do not claim convergence or scientific validity merely because the scheduler reports completion.

These examples guide wording only; they do not authorize marking an unfinished step completed, skipping validation, inventing a next action or rewriting already committed summaries.

### Plan invariants

Each `write_todos` call replaces the entire plan and must contain the complete latest list.

- While unfinished work remains, exactly one item must be `in_progress`.
- All other unfinished items must be `pending`.
- A new plan must mark its first actionable item `in_progress`.
- Completed items must remain unchanged in every later update.
- Remove pending items that are no longer required.
- If the current `in_progress` item becomes unnecessary, remove it only in an update that also activates another required item.
- Write every item `content` as one natural, complete, user-facing Chinese action sentence, preferably 15-50
  Chinese characters and never more than 60 characters.
- Each sentence should explain the action, its business or scientific object, and its immediate goal. Include known
  software, algorithms, input data, important parameters, target properties, or deliverables when useful; do not
  invent unknown details.
- Keep steps at the level of meaningful workflow outcomes rather than individual tool calls. Do not expose internal
  tool names, skill names, function names, implementation stages, or long file paths.
- Avoid generic placeholders such as "确认计算方案", "准备输入文件", "分析计算结果", or
  "生成计算报告" when the current context supports a more concrete description.

### State transitions

The plan must describe the work happening now, not work that already happened.

Before performing a planned step or calling a tool for it, make sure its item is already `in_progress`. If it is `pending`, call `write_todos` separately and wait for the update before continuing.

Immediately after completing a step, call `write_todos` to mark it `completed` and mark the next required item `in_progress` in the same update. Do not start the next step before this update succeeds.

As soon as a step's goal has been met, immediately call `write_todos` to mark that step `completed` with a
verified `summary` and activate the next required step as `in_progress`. Do not continue with later-step work
or pause for user input before this update succeeds.

#### Pending-item fallback

Never change an item directly from `pending` to `completed`:

- If the item was not performed and is no longer meaningful or needed, remove it from the plan.
- If the item was accidentally performed and completed early, first call `write_todos` separately to mark it `in_progress`. After that call returns, output only "<item content>已经执行完成" in the assistant text, then call `write_todos` again to mark it `completed` and activate the next required item.

Do not perform business work between these updates. This fallback does not authorize executing later items early.

Never call `write_todos` in parallel with another tool. If the plan becomes inaccurate, pause new work and update it first.

Do not mark failed, blocked, incomplete, or unverified work as `completed`. When waiting for user input, an external process, or error resolution, keep the corresponding item `in_progress` unless that item is removed through an explicit plan revision.

#### Skipped steps

Only mark a step `skipped` when the system injects a `[BUILD_ACTION]` instruction explicitly telling you that the user chose to skip that step via an action card. Never skip a step on your own. When a business failure occurs but the user has not chosen to skip, keep the item `in_progress` or wait for user decision. After skipping, preserve the full plan and continue executing subsequent steps.

### Completion

If a plan exists, do not complete its final item until all required work is finished, including result generation, verification, report generation, and required previews.

After all planned work is complete, call `write_todos` one final time and mark every item `completed` (or `skipped` for items the user chose to skip).

In that final update, set the last step's `summary` to its brief verified outcome; do not invent a next step. After the call returns, provide one concise final assistant delivery summary of the whole task: verified outcomes, delivered files or reports, material limitations, and any required next action. This also applies to scientific computation workflows. Do not reproduce every step's summary or the full report. Closing the plan does not end the response; finish the overall delivery summary before ending the turn."""


def _write_todos_with_summaries(runtime: ToolRuntime, todos: list[ExtendedTodo]) -> Command:
    # Keep the upstream whole-plan replacement and statuses. Only fill an
    # omitted result on an unchanged completed item from the committed state.
    updated = preserve_completed_summaries(runtime.state.get("todos"), [todo.model_dump() for todo in todos])
    return Command(update={
        "todos": updated,
        "messages": [ToolMessage(
            content=f"Updated todo list to {updated}",
            tool_call_id=runtime.tool_call_id,
        )],
    })


async def _awrite_todos_with_summaries(runtime: ToolRuntime, todos: list[ExtendedTodo]) -> Command:
    return _write_todos_with_summaries(runtime, todos)


def build_write_todos_middleware() -> TodoListMiddleware:
    """Build the todo middleware with the project-owned prompt overrides and skipped status support."""
    middleware = TodoListMiddleware(
        system_prompt=WRITE_TODOS_SYSTEM_PROMPT,
        tool_description=WRITE_TODOS_TOOL_DESCRIPTION,
    )
    middleware.tools[0] = middleware.tools[0].model_copy(
        update={
            "args_schema": ExtendedWriteTodosInput,
            "func": _write_todos_with_summaries,
            "coroutine": _awrite_todos_with_summaries,
        }
    )
    return middleware


__all__ = [
    "ExtendedTodo",
    "ExtendedWriteTodosInput",
    "WRITE_TODOS_SYSTEM_PROMPT",
    "WRITE_TODOS_TOOL_DESCRIPTION",
    "build_write_todos_middleware",
]

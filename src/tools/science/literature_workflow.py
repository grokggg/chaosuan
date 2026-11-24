"""Scientific literature workflow extraction tools."""

import json
import re
import time
from typing import Annotated, Any, Literal

from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import build_once_chat_openai
from src.logger import get_logger
from src.tools.document import _parse_file
from src.utils import add_usage, extract_response_usage, load_current_llm_config, log_usage

logger = get_logger(__name__)

LITERATURE_CONTENT_MAX_CHARS = 30_000

WorkflowDomain = Literal["bioinformatics", "materials_science", "industrial_simulation", "general"]

EXTRACT_WORKFLOW_FROM_LITERATURE_DESCRIPTION = """从论文 PDF 中提取可复现的计算工作流。

当用户要求复现、重现、重新运行、实现或遵循论文中描述的计算流程时，使用上传论文的 PDF 路径调用本工具。
本工具会自行读取 PDF、判断相关领域，并提取后续计算所需的工作流。
"""

SUPPORTED_DOMAINS: tuple[WorkflowDomain, ...] = (
    "bioinformatics",
    "materials_science",
    "industrial_simulation",
    "general",
)
DOMAIN_CLASSIFICATION_CONTENT_LIMIT = 12000

DOMAIN_CLASSIFICATION_PROMPT = """请判断应使用哪一种领域规则，从论文中提取用户指定的计算场景工作流。

计算场景：
{scene}

可选领域：
- bioinformatics：生物信息学。典型线索包括测序、组学、基因、蛋白、样本、比对、富集分析、生信数据库。
- materials_science：材料科学。典型线索包括晶体结构、第一性原理、DFT、分子动力学、势函数、材料表征、材料数据库。
- industrial_simulation：工业仿真。典型线索包括 CAD、网格、边界条件、有限元、CFD、多物理场、求解器、收敛性。
- general：通用计算。无法归入以上三类、证据不足，或者目标流程主要是通用算法、数据处理、机器学习时使用。

判断原则：
- 判断“计算场景对应的目标工作流”，而不是只根据论文标题判断整篇论文。
- 论文可能横跨多个领域，但只能选择最适合目标工作流的一项。
- 不要使用论文外部知识。
- 依据应简洁列出论文片段或计算场景中的判断线索。
- 只输出严格 JSON，不要输出 Markdown 代码块或其他内容。

输出格式：
{{
  "领域": "bioinformatics | materials_science | industrial_simulation | general",
  "依据": ["值"]
}}

论文内容：
{content}
"""

BIOINFORMATICS_WORKFLOW_EXTRACTION_PROMPT = """你是一位生物信息学专家，请从论文内容中提取指定计算场景的生物信息分析工作流。

计算场景：
{scene}

要求：
- 只提取与“计算场景”相关的分析流程。
- 整理输入数据、输入数据的元信息，软件数据库不作为输入数据。
- 请以有向无环图的方式呈现分析流程，不同测序平台或者不同类型的测序数据分别作为起点。
- 湿实验部分不纳入分析流程，测序数据生产不纳入分析流程。
- “测序数据获取或下载”不纳入分析流程。
- 输入数据不作为单个节点。
- 单个步骤尽可能只使用单个软件。
- 对应有向无环图的每个节点，整理节点属性：节点编号、节点名称、分析内容、分析目的、分析结果、软件名称、软件参考文献、需要的生信数据库。
- 节点编号与有向无环图中的字母编号保持一致。
- “软件名称”仅保留完整名称。
- 节点名称不包含软件名称。
- “软件参考文献”仅保留完整文献标题，去除作者、期刊、日期等多余字符。
- 如果软件为 R package，在“软件名称”列的软件后加字符“(R)”。
- 如果软件为 Python package，在“软件名称”列的软件后加字符“(Python)”。
- 不是 Python、R package 的软件保持软件名称即可。
- 所有信息只能来源于论文内容，不要扩展、推测或补充外部知识。
- 缺失的信息填充“-”。
- 尽可能使用中文。
- 输出 JSON 的 key 也尽可能使用中文。
- 不输出无关信息，不要输出 Markdown 代码块。

输出结果必须是严格 JSON，且顶层 key 必须保持如下结构：
{{
  "输入数据": [
    {{
      "数据类型": "值",
      "来源": "值",
      "备注": "值"
    }}
  ],
  "DAG": {{
    "nodes": [
      {{
        "节点编号": "A",
        "节点名称": "值",
        "分析内容": "值",
        "分析目的": "值",
        "分析结果": "值",
        "软件名称": "值",
        "软件参考文献": "值",
        "需要的生信数据库": "值"
      }}
    ],
    "edges": [
      {{
        "source": "A",
        "target": "B"
      }}
    ]
  }}
}}

论文内容：
{content}
"""

MATERIALS_SCIENCE_WORKFLOW_EXTRACTION_PROMPT = """你是一位计算材料科学专家，请从论文内容中提取指定计算场景的材料科学计算工作流。

计算场景：
{scene}

要求：
- 只提取与“计算场景/计算方法/Computational Methods”相关的计算流程。
- 整理输入数据及其元信息，例如材料组成、晶体结构、实验数据、初始构型；软件和计算资源不作为输入数据。
- 请以有向无环图的方式呈现流程，不同结构、组成或数据类型可以分别作为起点。
- 实验制备、材料表征操作和数据获取或下载不纳入计算流程；实验数据被后续计算使用时应保留为输入数据。
- 输入数据不作为单个节点。
- 单个步骤尽可能只使用单个软件。
- 对应有向无环图的每个节点，整理节点属性：节点编号、节点名称、计算内容、计算目的、计算结果、软件名称、软件参考文献、所需资源、计算方法、关键参数。
- “所需资源”可包括论文明确提及的材料数据库、赝势、势函数、基组、模型或参数文件。
- 节点编号与有向无环图中的字母编号保持一致。
- “软件名称”仅保留完整名称，节点名称不包含软件名称。
- “软件参考文献”仅保留完整文献标题，去除作者、期刊、日期等多余字符。
- 所有信息只能来源于论文内容，不要扩展、推测或补充外部知识。
- 缺失的信息填充“-”。
- 尽可能使用中文。
- 输出 JSON 的 key 也尽可能使用中文。
- 不输出无关信息，不要输出 Markdown 代码块。
输出结果必须是严格 JSON，且顶层 key 必须保持如下结构：
{{
  "输入数据": [
    {{
      "数据类型": "值",
      "来源": "值",
      "备注": "值"
    }}
  ],
  "DAG": {{
    "nodes": [
      {{
        "节点编号": "A",
        "节点名称": "值",
        "计算内容": "值",
        "计算目的": "值",
        "计算结果": "值",
        "软件名称": "值",
        "软件参考文献": "值",
        "所需资源": "值",
        "关键参数": "值"
      }}
    ],
    "edges": [
      {{
        "source": "A",
        "target": "B"
      }}
    ]
  }}
}}
论文内容：
{content}
"""

INDUSTRIAL_SIMULATION_WORKFLOW_EXTRACTION_PROMPT = """你是一位工业仿真专家，请从论文内容中提取指定计算场景的仿真分析工作流

计算场景：
{scene}

要求：

- 只提取与"计算场景"相关的仿真计算流程。
- 整理输入数据、输入数据的元信息，商业软件许可证信息不作为输入数据。
- 请以有向无环图的方式呈现分析流程，不同物理场或不同类型的仿真分别作为起点。
- 实验测量部分不纳入分析流程，物理样机制备不纳入分析流程。
- "模型导入或几何获取"不纳入分析流程。
- 输入数据不作为单个节点。
- 单个步骤尽可能只使用单个软件/求解器。
- 对应有向无环图的每个节点，整理节点属性：节点编号、节点名称、分析内容、分析目的、分析结果、软件名称、软件参考文献、需要的材料数据库。
- 节点编号与有向无环图中的字母编号保持一致。
- "软件名称"仅保留完整名称。
- 节点名称不包含软件名称。
- "软件参考文献"仅保留完整文献标题，去除作者、期刊、日期等多余字符。
- 如果软件为MATLAB工具箱，在"软件名称"列的软件后加字符"(MATLAB)"。
- 如果软件为Python包，在"软件名称"列的软件后加字符"(Python)"。
- 不是Python、MATLAB工具箱的软件保持软件名称即可。
- 所有信息只能来源于论文内容，不要扩展、推测或补充外部知识。
- 缺失的信息填充"-"。
- 尽可能使用中文。
- 输出JSON的key也尽可能使用中文。
- 不输出无关信息，不要输出Markdown代码块。

输出结果必须是严格JSON，且顶层key必须保持如下结构：
{{
  "输入数据": [
    {{
      "数据类型": "值",
      "来源": "值",
      "备注": "值"
    }}
  ],
  "DAG": {{
    "nodes": [
      {{
        "节点编号": "A",
        "节点名称": "值",
        "分析内容": "值",
        "分析目的": "值",
        "分析结果": "值",
        "软件名称": "值",
        "软件参考文献": "值",
        "需要的材料数据库": "值"
      }}
    ],
    "edges": [
      {{
        "source": "A",
        "target": "B"
      }}
    ]
  }}
}}

论文内容：
{content}

"""

GENERAL_WORKFLOW_EXTRACTION_PROMPT = """你是一位严谨的科研计算工作流分析专家，请从论文内容中提取指定计算场景的通用计算工作流。

计算场景：
{scene}

要求：
- 只提取与“计算场景”相关的计算流程。
- 整理输入数据及其元信息；软件和计算资源不作为输入数据。
- 请以有向无环图的方式呈现流程，不同类型的输入数据可以分别作为起点。
- 实验操作、物理过程和数据获取或下载不纳入计算流程；实验数据被后续计算使用时应保留为输入数据。
- 输入数据不作为单个节点。
- 单个步骤尽可能只使用单个软件、代码库或模型。
- 对应有向无环图的每个节点，整理节点属性：节点编号、节点名称、计算内容、计算目的、计算结果、软件名称、软件参考文献、所需资源、关键参数。
- “所需资源”可包括论文明确提及的数据库、模型、配置文件、参数文件或外部依赖。
- 节点编号与有向无环图中的字母编号保持一致。
- “软件名称”仅保留完整名称，节点名称不包含软件名称。
- “软件参考文献”仅保留完整文献标题，去除作者、期刊、日期等多余字符。
- 所有信息只能来源于论文内容，不要扩展、推测或补充外部知识。
- 缺失的信息填充“-”。
- 尽可能使用中文。
- 输出 JSON 的 key 也尽可能使用中文。
- 不输出无关信息，不要输出 Markdown 代码块。

输出结果必须是严格 JSON，且顶层 key 必须保持如下结构：
{{
  "输入数据": [
    {{
      "数据类型": "值",
      "来源": "值",
      "备注": "值"
    }}
  ],
  "DAG": {{
    "nodes": [
      {{
        "节点编号": "A",
        "节点名称": "值",
        "计算内容": "值",
        "计算目的": "值",
        "计算结果": "值",
        "软件名称": "值",
        "软件参考文献": "值",
        "所需资源": "值",
        "关键参数": "值"
      }}
    ],
    "edges": [
      {{
        "source": "A",
        "target": "B"
      }}
    ]
  }}
}}

论文内容：
{content}
"""

WORKFLOW_EXTRACTION_PROMPTS: dict[WorkflowDomain, str] = {
    "bioinformatics": BIOINFORMATICS_WORKFLOW_EXTRACTION_PROMPT,
    "materials_science": MATERIALS_SCIENCE_WORKFLOW_EXTRACTION_PROMPT,
    "industrial_simulation": INDUSTRIAL_SIMULATION_WORKFLOW_EXTRACTION_PROMPT,
    "general": GENERAL_WORKFLOW_EXTRACTION_PROMPT,
}

EXTRACTION_SYSTEM_MESSAGES: dict[WorkflowDomain, str] = {
    "bioinformatics": "你是严谨的生物信息学工作流抽取助手，只输出符合要求的 JSON。",
    "materials_science": "你是严谨的材料科学计算工作流抽取助手，只输出符合要求的 JSON。",
    "industrial_simulation": "你是严谨的工业仿真工作流抽取助手，只输出符合要求的 JSON。",
    "general": "你是严谨的科研计算工作流抽取助手，只输出符合要求的 JSON。",
}


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def _log_llm_usage(phase: str, response: Any, *, elapsed_seconds: float) -> dict[str, int]:
    return log_usage(
        logger,
        "Literature workflow LLM usage",
        extract_response_usage(response),
        elapsed_seconds=elapsed_seconds,
        phase=phase,
    )


def _extract_json_text(value: str) -> str:
    text = value.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()

    decoder = json.JSONDecoder()
    try:
        _, end = decoder.raw_decode(text)
        return text[:end]
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start < 0:
        raise ValueError("模型输出中未找到 JSON 对象")
    payload, end = decoder.raw_decode(text[start:])
    return json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else text[start : start + end]


def _normalize_model_output(value: str) -> dict[str, Any]:
    json_text = _extract_json_text(value)
    json_text = json_text.replace("((Python))", "(Python)")
    json_text = json_text.replace("((R))", "(R)")
    payload = json.loads(json_text)
    if not isinstance(payload, dict):
        raise ValueError("模型输出 JSON 顶层必须是对象")
    return payload


def _build_classification_excerpt(content: str) -> str:
    return content[:DOMAIN_CLASSIFICATION_CONTENT_LIMIT]


def _normalize_domain_decision(value: str) -> dict[str, Any]:
    payload = _normalize_model_output(value)
    domain = payload.get("领域")
    if domain not in SUPPORTED_DOMAINS:
        raise ValueError(f"模型返回了不支持的领域: {domain}")

    raw_evidence = payload.get("依据", [])
    evidence = [str(item) for item in raw_evidence] if isinstance(raw_evidence, list) else [str(raw_evidence)]
    return {
        "领域": domain,
        "依据": evidence,
        "自动判断": True,
    }


async def _classify_workflow_domain(llm: Any, content: str, scene: str) -> dict[str, Any]:
    try:
        messages = [
            SystemMessage(content="你是严谨的科研计算工作流领域分类助手，只输出符合要求的 JSON。"),
            HumanMessage(
                content=DOMAIN_CLASSIFICATION_PROMPT.format(
                    content=_build_classification_excerpt(content),
                    scene=scene,
                )
            ),
        ]
        started_at = time.perf_counter()
        response = await llm.ainvoke(messages)
        usage = _log_llm_usage(
            "domain_classification",
            response,
            elapsed_seconds=time.perf_counter() - started_at,
        )
        decision = _normalize_domain_decision(_message_content_to_text(response.content))
        decision["_usage"] = usage
        logger.info(
            "Literature workflow domain selected: domain=%s",
            decision["领域"],
        )
        return decision
    except Exception as exc:
        logger.warning("Failed to classify literature workflow domain; using general profile", exc_info=True)
        return {
            "领域": "general",
            "依据": [f"领域自动判断失败，已回退通用规则：{type(exc).__name__}: {exc}"],
            "自动判断": True,
        }


def _error_result(message: str, *, raw_output: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "error",
        "message": message,
    }
    if raw_output:
        result["raw_output"] = raw_output[:4000]
    return result


def _read_literature_pdf_content(pdf_link: str) -> str:
    _, content, ok = _parse_file(pdf_link, LITERATURE_CONTENT_MAX_CHARS)
    if not ok:
        raise ValueError(content)
    return content[:LITERATURE_CONTENT_MAX_CHARS]


@tool(
    "extract_workflow_from_literature",
    description=EXTRACT_WORKFLOW_FROM_LITERATURE_DESCRIPTION,
)
async def extract_workflow_from_literature(
    pdf_link: Annotated[
        str,
        "论文 PDF 文件链接或路径。应来自对话上下文中的 efile 文件信息，仅支持路径。",
    ],
    scene: Annotated[
        str,
        "需要提取并复现的计算场景，例如 RNA-seq 差异表达分析、晶体结构弛豫、流体仿真、有限元分析或模型训练。",
    ],
) -> dict[str, Any]:
    """Extract a domain-specific computational workflow JSON from a literature PDF."""

    tool_started_at = time.perf_counter()
    total_usage: dict[str, int] = {}
    try:
        if not pdf_link.strip():
            return _error_result("pdf_link must not be empty")
        if not scene.strip():
            return _error_result("scene must not be empty")

        content = _read_literature_pdf_content(pdf_link.strip())
        llm = build_once_chat_openai(load_current_llm_config())
        domain_decision = await _classify_workflow_domain(llm, content.strip(), scene.strip())
        add_usage(
            total_usage, domain_decision.get("_usage") if isinstance(domain_decision.get("_usage"), dict) else None
        )
        selected_domain: WorkflowDomain = domain_decision["领域"]
        visible_domain_decision = {key: value for key, value in domain_decision.items() if key != "_usage"}
        messages = [
            SystemMessage(content=EXTRACTION_SYSTEM_MESSAGES[selected_domain]),
            HumanMessage(
                content=WORKFLOW_EXTRACTION_PROMPTS[selected_domain].format(
                    content=content.strip(),
                    scene=scene.strip(),
                )
            ),
        ]

        extraction_started_at = time.perf_counter()
        response = await llm.ainvoke(messages)
        extraction_usage = _log_llm_usage(
            "workflow_extraction",
            response,
            elapsed_seconds=time.perf_counter() - extraction_started_at,
        )
        add_usage(total_usage, extraction_usage)
        raw_output = _message_content_to_text(response.content)
        return {
            "领域判断": visible_domain_decision,
            **_normalize_model_output(raw_output),
        }
    except Exception as exc:
        logger.exception("Failed to extract literature workflow")
        return _error_result(f"{type(exc).__name__}: {exc}", raw_output=locals().get("raw_output"))
    finally:
        log_usage(
            logger,
            "Literature workflow tool finished",
            total_usage,
            elapsed_seconds=time.perf_counter() - tool_started_at,
        )


__all__ = ["extract_workflow_from_literature"]

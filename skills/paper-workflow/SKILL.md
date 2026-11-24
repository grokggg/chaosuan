---
name: paper-workflow
description: 当用户要求搜索论文、查找文献、下载开放论文 PDF，并从论文中提取可复现计算流程、实验流程、算法流程或科研计算 DAG 时使用。优先调用模板工具 search_academic_papers 搜索论文；只下载最相关的一篇合法开放 PDF 到 ${HOME}/workspace；然后调用 extract_workflow_from_literature 分析论文计算流程。
---

# Paper Workflow | 论文搜索、下载与计算流程提取

本技能负责把“找论文并提取论文里的可复现计算流程”串成一个轻量流程。不要复制论文全文，不要批量下载 PDF。

## 工具与资源

- 论文搜索：直接调用工具 `search_academic_papers`，实现位于 `src/tools/paper_search.py`。
- 论文下载：使用本技能脚本 `scripts/download_open_paper.py`，该脚本复用 `download-paper` 的开放 PDF 下载逻辑。
- 流程分析：直接调用工具 `extract_workflow_from_literature`，实现位于 `src/tools/literature_workflow.py`。
- 下载目录：必须使用 `${HOME}/workspace/papers`。

## 决策流程

1. 如果用户只要论文列表、推荐文献或检索结果，只调用 `search_academic_papers`，不要下载 PDF。
2. 如果用户要“分析论文流程、复现论文、提取计算流程、实验流程、算法步骤、DAG、软件依赖”，先调用 `search_academic_papers` 搜索候选。
3. 从候选中只选择最相关的一篇进入下载阶段。优先选择用户明确点名的论文；否则按问题匹配度、开放 PDF 可用性、引用数和年份综合判断。
4. 下载成功一篇 PDF 后立即停止，不继续下载其他候选。
5. 将下载得到的 `output_path` 作为 `pdf_link` 传给 `extract_workflow_from_literature`，并把用户要复现或提取的计算场景作为 `scene`。

## 搜索阶段

调用：

```text
search_academic_papers(query=<用户主题或论文关键词>, source="both", max_results=10)
```

搜索结果中优先关注：

- `title`
- `authors`
- `year`
- `doi`
- `url`
- `open_access_url`
- `abstract`
- `citation_count`

如果没有可下载开放 PDF，也可以只基于摘要、论文元数据和用户提供的资料继续轻量分析，但不要声称已经阅读全文。

## 下载阶段

只把一篇最终候选的 DOI、OpenAlex ID、arXiv URL 或开放 PDF URL 交给下载脚本。

使用系统提示词提供的当前项目根目录绝对路径替换下面命令中的 `<PROJECT_ROOT>`。

```bash
python3 "<PROJECT_ROOT>/skills/paper-workflow/scripts/download_open_paper.py" "<identifier>" --out-dir "$HOME/workspace/papers"
```

脚本输出 JSON。只有当 `status` 为 `downloaded` 时，才把 `output_path` 传入后续论文流程分析。

如果最相关论文返回 `no_open_pdf`，按相关性尝试下一篇候选；成功下载一篇后停止。不得使用 Sci-Hub、付费墙绕过、机构账号或需要登录授权的来源。

## 流程分析阶段

调用：

```text
extract_workflow_from_literature(pdf_link=<downloaded output_path>, scene=<用户要提取或复现的计算场景>)
```

`scene` 应该具体，例如：

- `RNA-seq 差异表达分析`
- `晶体结构弛豫和能带计算`
- `CFD 流体仿真流程`
- `模型训练与评估流程`

输出时优先保留 `extract_workflow_from_literature` 的 JSON 结构，包括领域判断、输入数据、DAG 节点和边。不要把 PDF 全文或大段原文复制给用户。

## 多篇论文请求

- 用户只要“找几篇论文”：返回搜索结果列表，不下载。
- 用户要比较多篇论文：优先基于标题、摘要、元数据、官方代码或 README 做轻量比较。
- 用户明确要求全文分析多篇：先说明默认只深入分析最相关的一篇；除非用户再次明确要求扩展，否则不要批量下载。

## 失败处理

- 搜索失败：说明 `search_academic_papers` 的错误来源，并建议更具体关键词、年份范围或用户提供 DOI/arXiv 链接。
- 下载失败：返回 `no_open_pdf` 原因，并改用摘要、官方代码、README、Papers with Code 或用户提供的合法 PDF。
- 流程分析失败：报告 `extract_workflow_from_literature` 返回的错误，并说明需要更清晰的 PDF、OCR 文本或更具体的计算场景。

---
name: academic-research-skills
description: "Router skill for the academic-research-skills bundle. Selects exactly one embedded skill for academic work: deep-research for research/literature/fact-checking, academic-paper for paper writing/revision/citations/formatting, academic-paper-reviewer for manuscript peer review, and academic-pipeline for end-to-end research-to-publication workflows."
---

# Academic Research Skills Router

This is the top-level Vibe Coding entry for the academic research bundle. Its job is routing: identify the user's current academic task, then read and follow the matching embedded `SKILL.md`.

Embedded skills:

- `deep-research/SKILL.md`
- `academic-paper/SKILL.md`
- `academic-paper-reviewer/SKILL.md`
- `academic-pipeline/SKILL.md`

## Routing Priority

Apply these rules in order. Stop at the first clear match.

| Priority | User intent / signal | Route to | Typical mode |
| --- | --- | --- | --- |
| 1 | User explicitly names a subskill or mode, such as `deep-research`, `academic-paper`, `reviewer`, `pipeline`, `systematic-review`, `revision`, `citation-check`, or `format-convert` | Named subskill | Named mode |
| 2 | User wants the whole journey: research to paper, full paper workflow, end-to-end paper, research-to-publication, complete manuscript pipeline | `academic-pipeline/SKILL.md` | stage-detected |
| 3 | User has a manuscript and asks for review, critique, referee report, editorial decision, peer review, journal-style review, methodology-only review, or "is this paper good?" | `academic-paper-reviewer/SKILL.md` | `full`, `quick`, `methodology-focus`, or `guided` |
| 4 | User has reviewer comments and asks to revise, respond to reviewers, parse comments, plan revisions, or make a revision roadmap | `academic-paper/SKILL.md` | `revision` or `revision-coach` |
| 5 | User asks to write, outline, plan, draft, abstract, introduction, methodology, discussion, thesis chapter, journal article, conference paper, citation check, AI disclosure, LaTeX/DOCX/PDF/Markdown conversion | `academic-paper/SKILL.md` | `plan`, `full`, `outline-only`, `abstract-only`, `citation-check`, `format-convert`, or `disclosure` |
| 6 | User asks for research, deep research, research question development, literature review, systematic review, meta-analysis, PRISMA, evidence synthesis, source verification, fact-checking, methodology exploration, or research monitoring | `deep-research/SKILL.md` | `socratic`, `full`, `quick`, `lit-review`, `systematic-review`, `fact-check`, or `review` |

## Route Boundaries

Use `deep-research` when the primary output is evidence, not a publishable manuscript:

- research question refinement
- literature search and annotated bibliography
- source verification and fact-checking
- cross-source synthesis, policy analysis, or APA-style research report
- systematic review or meta-analysis planning/execution

Use `academic-paper` when the primary output is a paper artifact:

- paper plan, outline, or full manuscript draft
- abstract, bilingual abstract, keywords
- section writing: introduction, methods, results, discussion
- citation audit, citation style conversion, reference cleanup
- LaTeX, DOCX, PDF, Markdown, cover letter, disclosure
- revision from reviewer/editor comments

Use `academic-paper-reviewer` when the primary output is an evaluation of an existing paper:

- simulated peer review or referee report
- editorial decision and revision roadmap
- quick paper quality assessment
- methodology/statistics-focused review
- re-review to check whether revisions addressed comments

Use `academic-pipeline` only when orchestration across multiple phases is requested or clearly needed:

- research -> write -> integrity check -> review -> revise -> re-review -> final integrity -> finalize
- user asks for an end-to-end workflow or wants the agent to manage stages
- user enters mid-pipeline with materials and wants the full process continued

Do not route to `academic-pipeline` for a single isolated task. The pipeline is optional and heavier than the single-purpose skills.

## Mode Delegation

This router does not decide detailed modes. After routing to an embedded skill, read that skill's `SKILL.md` and let it choose the mode from its own trigger and mode-selection rules.

Only preserve an explicitly requested mode from the user. For example:

- `systematic-review` -> route to `deep-research/SKILL.md`, then follow its `systematic-review` mode.
- `revision` or `revision-coach` -> route to `academic-paper/SKILL.md`, then follow its revision rules.
- `re-review` -> route to `academic-paper-reviewer/SKILL.md`, then follow its re-review rules.
- `research-to-publication` or `full pipeline` -> route to `academic-pipeline/SKILL.md`, then follow its stage detection.

## Ambiguity Handling

- If the user asks for "help with my paper" and no artifact/stage is clear, ask one short question to identify whether they need research, writing, review, or full pipeline.
- If the user provides only a topic and asks for a paper, use `academic-paper` `plan` unless they explicitly want a full research-to-publication process.
- If the user provides a paper and asks to "improve it", route to `academic-paper` `revision`; if they ask to "review/critique/evaluate it", route to `academic-paper-reviewer`.
- If the user asks for literature review, decide by output type: source synthesis/report goes to `deep-research`; manuscript-style literature review paper goes to `academic-paper`.
- If the user asks for both research and paper drafting in one request, route to `academic-pipeline` when they want stage management; otherwise start with `deep-research` and hand off to `academic-paper`.

## Execution Rules

1. Read the selected embedded `SKILL.md` before doing substantive work.
2. Read additional embedded references only when the selected `SKILL.md` requires them.
3. Preserve user-provided discipline, topic, research question, target venue, citation style, language, word count, and output format.
4. Do not invent citations, DOIs, datasets, page numbers, quotations, journal policies, reviewer identities, or empirical results.
5. For factual research and citation claims, use available search, RAG, uploaded files, or local sources. Clearly separate verified evidence from assumptions.
6. When using `academic-pipeline`, maintain stage state and follow its checkpoint and integrity-gate rules.
7. When a task spans multiple embedded skills outside the pipeline, make the handoff explicit: summarize completed artifacts and name the next skill/mode.

## Non-Triggers

Do not use this skill for ordinary coding, deployment, data engineering, UI design, or system administration tasks unless the actual user goal is academic research, scholarly writing, manuscript review, or research publication workflow.

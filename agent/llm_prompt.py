"""Prompt builder for future evidence-grounded LLM responses.

The project currently has a deterministic response generator.  This module
prepares the boundary for an LLM without calling any external API: it packages
student state, planned tasks, risks, and official evidence into a prompt that
instructs the model to stay grounded in cited sources.
"""

from __future__ import annotations

from pathlib import Path

from agent.intent_router import IntentResult
from agent.rag_retriever import RetrievalResult
from agent.risk_checker import RiskItem
from agent.task_planner import PlannedTask, StudentProfile


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LLM_PROMPT_PATH = ROOT_DIR / "data" / "metadata" / "last_llm_prompt.md"


def build_grounded_prompt(
    *,
    query: str,
    intent: IntentResult,
    profile: StudentProfile,
    tasks: list[PlannedTask],
    risks: list[RiskItem],
    evidence: list[RetrievalResult],
) -> str:
    """Build a source-grounded prompt for a future LLM call."""

    lines = [
        "# Role",
        "你是面向内地港校授课型硕士 offer holder 的入学准备助手。",
        "",
        "# Non-negotiable rules",
        "- 只能基于下方 task / risk / official evidence 作答。",
        "- 如果没有证据支持具体日期、金额、材料或资格，不要编造；请明确说“当前本地官方归档未找到”。",
        "- 对 deadline、费用、签证、住宿、注册等高风险事项，必须提醒用户以 offer letter、学校 portal、学院邮件和官方 URL 为准。",
        "- 每个涉及 deadline、金额、材料、资格、操作步骤或风险的具体结论，都必须绑定 Evidence ID 和 source_url。",
        "- 如果 task/risk 模板与 official evidence 不一致，以 official evidence 为准；没有 evidence 时只能给通用提醒，不能说成学校官方规则。",
        "- user_task_status、user_deadline_at、user_reminder_at 是用户侧记录；official_deadline_evidence 是官方候选证据，二者不能混同。",
        "- evidence_quality_status 与 usable/review/rejected counts 只表示本地规则审计结果；review/rejected evidence 不能被当作官方结论。",
        "- 输出应是中文，结构包括：当前判断、下一步任务、风险提醒、官方来源。",
        "- 每条关键建议必须附 source_url；没有 source_url 时说明当前本地官方归档未找到可引用来源。",
        "",
        "# User query",
        query.strip(),
        "",
        "# Parsed intent and profile",
        f"- school: {profile.school or intent.school or ''}",
        f"- stage: {intent.stage or ''}",
        f"- intent: {intent.intent}",
        f"- origin: {profile.origin}",
        f"- program_type: {profile.program_type}",
        f"- completed_flags: {', '.join(sorted(profile.completed_flags)) or 'none'}",
        f"- has_conditional_offer: {profile.has_conditional_offer}",
        "",
        "# Planned tasks",
    ]

    if tasks:
        for index, task in enumerate(tasks[:8], start=1):
            lines.extend(
                [
                    f"## Task {index}: {task.task_name}",
                    f"- task_id: {task.task_id}",
                    f"- stage: {task.stage}",
                    f"- risk_level: {task.risk_level}",
                    f"- trigger_condition: {task.trigger_condition}",
                    f"- deadline: {task.deadline}",
                    f"- required_documents: {task.required_documents}",
                    f"- action_url: {task.action_url}",
                    f"- source_url: {task.source_url}",
                    f"- reason: {task.reason}",
                    f"- task_code: {task.task_code}",
                    f"- enrichment_status: {task.enrichment_status}",
                    f"- evidence_count: {task.evidence_count}",
                    f"- candidate_evidence_count: {task.candidate_evidence_count}",
                    f"- usable_evidence_count: {task.usable_evidence_count}",
                    f"- review_evidence_count: {task.review_evidence_count}",
                    f"- rejected_evidence_count: {task.rejected_evidence_count}",
                    f"- evidence_quality_status: {task.evidence_quality_status}",
                    f"- evidence_quality_notes: {task.evidence_quality_notes}",
                    f"- official_deadline_evidence: {task.official_deadline_evidence}",
                    f"- official_document_evidence: {task.official_document_evidence}",
                    f"- official_action_evidence: {task.official_action_evidence}",
                    f"- official_action_urls: {task.official_action_urls}",
                    f"- official_fee_evidence: {task.official_fee_evidence}",
                    f"- user_task_status: {task.user_task_status}",
                    f"- user_deadline_at: {task.user_deadline_at}",
                    f"- user_deadline_timezone: {task.user_deadline_timezone}",
                    f"- user_deadline_source: {task.user_deadline_source}",
                    f"- user_reminder_at: {task.user_reminder_at}",
                    f"- user_reminder_status: {task.user_reminder_status}",
                    f"- user_task_notes: {task.user_task_notes}",
                    "",
                ]
            )
    else:
        lines.append("- No planned tasks available.")
        lines.append("")

    lines.append("# Risks")
    if risks:
        for risk in risks[:8]:
            lines.extend(
                [
                    f"- [{risk.level}] {risk.title}",
                    f"  - detail: {risk.detail}",
                    f"  - mitigation: {risk.mitigation}",
                    f"  - source_url: {risk.source_url}",
                ]
            )
    else:
        lines.append("- No risk items available.")
    lines.append("")

    lines.append("# Official evidence")
    if evidence:
        for index, item in enumerate(evidence[:10], start=1):
            chunk = item.chunk
            source_url = item.source_url or chunk.final_url
            lines.extend(
                [
                    f"## Evidence {index}",
                    f"- school: {chunk.school}",
                    f"- page_type: {chunk.page_type}",
                    f"- stage: {chunk.stage}",
                    f"- title: {chunk.title}",
                    f"- score: {item.score:.2f}",
                    f"- source_url: {source_url}",
                    f"- evidence_id: Evidence {index}",
                    f"- chunk_id: {chunk.chunk_id}",
                    f"- matched_terms: {', '.join(item.matched_terms) or 'none'}",
                    "```text",
                    _trim(chunk.text, 900),
                    "```",
                    "",
                ]
            )
    else:
        lines.append("- No official evidence retrieved.")
        lines.append("")

    lines.extend(
        [
            "# Desired answer",
            "请基于以上信息生成给学生的中文回答。不要提及内部字段名，除非字段名本身对用户有帮助。",
            "输出结构固定为：当前判断、下一步任务、风险提醒、官方来源。",
            "下一步任务和风险提醒里的每条具体建议后面都要附可核验的 source_url；可用“（来源：...）”这种稳定格式。",
            "如果某条建议没有 source_url，就明确写“当前本地官方归档未找到可引用来源”，不要伪造 citation。",
        ]
    )
    return "\n".join(lines)


def write_grounded_prompt(prompt: str, output_path: Path | str = DEFAULT_LLM_PROMPT_PATH) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(prompt, encoding="utf-8")


def _trim(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."

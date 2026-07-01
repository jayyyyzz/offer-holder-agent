"""Chinese response formatting for the first runnable offer-holder agent."""

from __future__ import annotations

from textwrap import shorten

from agent.intent_router import IntentResult
from agent.rag_retriever import RetrievalResult
from agent.risk_checker import RiskItem
from agent.task_planner import PlannedTask, StudentProfile


def format_agent_response(
    *,
    query: str,
    intent: IntentResult,
    profile: StudentProfile,
    tasks: list[PlannedTask],
    risks: list[RiskItem],
    evidence: list[RetrievalResult],
) -> str:
    """Render a concise Chinese answer with official-source evidence."""

    lines: list[str] = []
    school_label = profile.school or intent.school or "未指定学校"
    stage_label = intent.stage or "综合入学准备"

    lines.append(f"我先按「{school_label} / {stage_label}」来处理你的问题。")
    lines.append(
        "提醒：这是基于本地归档的港校官方页面生成的初步任务建议；具体金额、日期和资格仍要以 offer letter、学校 portal 和学院邮件为准。"
    )
    lines.append("")

    if tasks:
        lines.append("下一步优先任务：")
        for index, task in enumerate(tasks[:5], start=1):
            lines.append(
                f"{index}. [{task.risk_level}] {task.task_name} —— {task.description}"
            )
            lines.append(f"   触发条件：{task.trigger_condition}")
            lines.append(f"   截止依据：{task.deadline}")
            lines.append(f"   需要材料：{task.required_documents}")
            if task.user_task_status:
                lines.append(f"   个人状态：{task.user_task_status}")
            if task.user_deadline_at:
                deadline = task.user_deadline_at
                if task.user_deadline_timezone:
                    deadline = f"{deadline} {task.user_deadline_timezone}"
                source = f"（来源：{task.user_deadline_source}）" if task.user_deadline_source else ""
                lines.append(f"   个人截止时间：{deadline}{source}")
            if task.user_reminder_at:
                reminder = task.user_reminder_at
                if task.user_reminder_status:
                    reminder = f"{reminder}（{task.user_reminder_status}）"
                lines.append(f"   提醒时间：{reminder}")
            if task.evidence_quality_status:
                lines.append(
                    "   证据质量："
                    f"{task.usable_evidence_count} 可用 / "
                    f"{task.review_evidence_count} 待复核 / "
                    f"{task.rejected_evidence_count} 已排除"
                )
            if task.official_deadline_evidence:
                lines.append(f"   官方 deadline 候选证据：{task.official_deadline_evidence}")
            if task.official_document_evidence:
                lines.append(f"   官方材料候选证据：{task.official_document_evidence}")
            if task.official_action_evidence:
                lines.append(f"   官方操作候选证据：{task.official_action_evidence}")
            if task.official_fee_evidence:
                lines.append(f"   官方费用候选证据：{task.official_fee_evidence}")
            if task.action_url:
                lines.append(f"   官方入口：{task.action_url}")
            lines.append(f"   排序原因：{task.reason}")
    else:
        lines.append("我还没有足够状态生成任务清单。你可以补充学校、是否已接受 offer、是否已交留位费、签证是否已递交。")

    if risks:
        lines.append("")
        lines.append("风险提醒：")
        for risk in risks[:5]:
            source = f" 来源：{risk.source_url}" if risk.source_url else ""
            lines.append(f"- [{risk.level}] {risk.title}：{risk.detail}")
            lines.append(f"  建议：{risk.mitigation}{source}")

    if evidence:
        lines.append("")
        lines.append("检索到的官方依据片段：")
        for result in evidence[:4]:
            snippet = clean_snippet(result.chunk.text)
            source = result.source_url or result.chunk.final_url
            lines.append(
                f"- {result.chunk.school} / {result.chunk.page_type} / {result.chunk.title} "
                f"(score={result.score:.1f})"
            )
            lines.append(f"  {snippet}")
            if source:
                lines.append(f"  来源：{source}")
    else:
        lines.append("")
        lines.append("本次没有检索到可用官方片段。可能需要先运行爬虫、构建 knowledge_base/chunks.csv，或补充该学校数据源。")

    lines.append("")
    lines.append("如果你愿意继续优化，可以下一条直接告诉我：学校、专业、offer 类型、已完成事项、开学月份，我会把任务清单收窄到你的个人状态。")
    return "\n".join(lines)


def ensure_source_citations(
    answer: str,
    *,
    tasks: list[PlannedTask],
    risks: list[RiskItem],
    evidence: list[RetrievalResult],
    limit: int = 6,
) -> str:
    if any(marker in answer for marker in ("http://", "https://", "官方来源", "来源：")):
        return answer

    urls = collect_source_urls(tasks=tasks, risks=risks, evidence=evidence, limit=limit)
    if not urls:
        return answer
    lines = [answer.rstrip(), "", "官方来源："]
    for url in urls:
        lines.append(f"- {url}")
    return "\n".join(lines)


def collect_source_urls(
    *,
    tasks: list[PlannedTask],
    risks: list[RiskItem],
    evidence: list[RetrievalResult],
    limit: int = 6,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        normalized = str(url or "").strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        urls.append(normalized)

    for task in tasks:
        add(task.source_url)
        for value in str(task.action_url or "").split("|"):
            add(value)
        for value in str(task.official_action_urls or "").split("|"):
            add(value)
    for risk in risks:
        add(risk.source_url)
    for item in evidence:
        add(item.source_url or item.chunk.final_url)
    return urls[:limit]


def clean_snippet(text: str, width: int = 260) -> str:
    compact = " ".join(text.split())
    return shorten(compact, width=width, placeholder="...")

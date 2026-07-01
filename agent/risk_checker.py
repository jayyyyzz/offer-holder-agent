"""Risk checks for offer-holder workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from agent.intent_router import IntentResult
from agent.rag_retriever import RetrievalResult
from agent.task_planner import PlannedTask, StudentProfile


@dataclass(frozen=True)
class RiskItem:
    level: str
    title: str
    detail: str
    related_stage: str
    mitigation: str
    source_url: str = ""


class RiskChecker:
    """Detect likely blockers from the user's coarse state."""

    def check(
        self,
        profile: StudentProfile,
        *,
        tasks: list[PlannedTask],
        evidence: list[RetrievalResult],
        intent: IntentResult | None = None,
    ) -> list[RiskItem]:
        risks: list[RiskItem] = []

        source_by_stage = _source_by_stage(tasks, evidence)

        if not profile.is_completed("accepted_offer"):
            risks.append(
                RiskItem(
                    level="high",
                    title="尚未确认接受 offer",
                    detail="如果 offer letter / portal 设有 acceptance deadline，错过后可能影响入学资格或奖学金/名额保留。",
                    related_stage="offer_acceptance",
                    mitigation="先登录学校申请系统核对接受 offer 与留位费截止日，并保存确认记录。",
                    source_url=source_by_stage.get("offer_acceptance", ""),
                )
            )

        if not profile.is_completed("paid_deposit"):
            risks.append(
                RiskItem(
                    level="high",
                    title="留位费状态未确认",
                    detail="不少 TPG offer 会把 deposit 与 acceptance 绑定；未按时付款可能被视为未接受录取。",
                    related_stage="offer_acceptance",
                    mitigation="核对 offer letter 金额、付款方式、到账要求和截止时间；付款后保留凭证。",
                    source_url=source_by_stage.get("offer_acceptance", ""),
                )
            )

        if profile.has_conditional_offer is True and not profile.is_completed("conditions_cleared"):
            risks.append(
                RiskItem(
                    level="high",
                    title="Conditional offer 材料可能是阻塞项",
                    detail="若最终学历、成绩单、语言成绩或官方认证未满足条件，学校可能无法把录取转为可注册状态。",
                    related_stage="offer_acceptance",
                    mitigation="逐条核对 conditional offer 的 pending conditions，优先处理耗时长的官方成绩单/认证文件。",
                    source_url=source_by_stage.get("offer_acceptance", ""),
                )
            )

        if profile.origin.lower().startswith("mainland") and not (
            profile.is_completed("visa_submitted") or profile.is_completed("visa_approved")
        ):
            risks.append(
                RiskItem(
                    level="high",
                    title="学生签证 / 进入许可尚未递交",
                    detail="内地学生通常需要 entry permit / student visa 才能以学生身份来港；处理周期不可完全由学生控制。",
                    related_stage="visa",
                    mitigation="尽早按学校签证页面准备申请表、旅行证件、录取证明和财力材料，递交后持续跟进。",
                    source_url=source_by_stage.get("visa", ""),
                )
            )

        if profile.is_completed("visa_submitted") and not profile.is_completed("visa_approved"):
            risks.append(
                RiskItem(
                    level="medium",
                    title="签证已递交但未获批",
                    detail="到港机票、住宿入住和 orientation 安排都依赖签证 / 进入许可状态。",
                    related_stage="visa",
                    mitigation="定期查看学校或入境处通知，避免在获批前购买不可退改的重要行程。",
                    source_url=source_by_stage.get("visa", ""),
                )
            )

        if not profile.is_completed("registered"):
            risks.append(
                RiskItem(
                    level="medium",
                    title="线上注册 / 学籍激活未完成",
                    detail="注册常与学生账号、课程、缴费、证件核验或到校流程相连。",
                    related_stage="registration",
                    mitigation="关注学校 registration guide 和学生系统开放时间，准备证件照片与身份证明文件。",
                    source_url=source_by_stage.get("registration", ""),
                )
            )

        if intent and intent.stage and not evidence:
            risks.append(
                RiskItem(
                    level="medium",
                    title="本地资料库未检索到足够官方依据",
                    detail="可能是该学校页面被 WAF 拦截、PDF 尚未抽取，或 source_list 仍需补充。",
                    related_stage=intent.stage,
                    mitigation="先打开 source_list 中对应官方页面人工核验；后续可加入 PDF 抽取或浏览器渲染采集。",
                )
            )

        return sorted(risks, key=lambda item: _risk_order(item.level))


def _source_by_stage(
    tasks: list[PlannedTask],
    evidence: list[RetrievalResult],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for task in tasks:
        mapping.setdefault(task.stage, task.source_url)
    for result in evidence:
        mapping.setdefault(result.chunk.stage, result.source_url)
    return mapping


def _risk_order(level: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(level, 3)


def generated_at() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

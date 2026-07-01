"""Lightweight intent routing for the HK offer-holder preparation agent.

This module deliberately uses transparent keyword rules instead of an LLM.
For the first runnable agent, the goal is to make every routing decision easy
to inspect and adjust while the data model is still evolving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable


SCHOOL_ALIASES: dict[str, tuple[str, ...]] = {
    "HKU": ("hku", "hong kong university", "university of hong kong", "港大", "香港大学"),
    "CUHK": ("cuhk", "chinese university", "中大", "香港中文大学", "港中文"),
    "HKUST": ("hkust", "ust", "science and technology", "科大", "香港科技大学", "港科大"),
    "CityU": ("cityu", "city university", "城大", "香港城市大学", "cityuhk"),
    "PolyU": ("polyu", "polytechnic", "理大", "香港理工大学"),
    "HKBU": ("hkbu", "baptist", "浸会", "香港浸会大学", "浸大"),
    "Lingnan": ("lingnan", "岭南", "岭南大学"),
    "EdUHK": ("eduhk", "education university", "教大", "香港教育大学"),
}


STAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "offer_acceptance": (
        "accept offer",
        "offer acceptance",
        "deposit",
        "admission offer",
        "conditional offer",
        "official document",
        "接受offer",
        "接受 offer",
        "录取",
        "留位费",
        "押金",
        "补交",
        "条件录取",
        "conditional",
        "材料",
    ),
    "visa": (
        "visa",
        "entry permit",
        "immigration",
        "id995a",
        "student visa",
        "non-local",
        "签证",
        "进入许可",
        "入境许可",
        "学生签",
        "逗留",
        "来港",
    ),
    "housing": (
        "accommodation",
        "housing",
        "hostel",
        "hall",
        "residence",
        "宿舍",
        "住宿",
        "舍堂",
        "学生公寓",
        "租房",
    ),
    "payment": (
        "tuition",
        "fee",
        "payment",
        "pay",
        "学费",
        "缴费",
        "付款",
        "银行",
        "账单",
        "费用",
    ),
    "registration": (
        "registration",
        "enrolment",
        "enrollment",
        "student account",
        "online registration",
        "注册",
        "学籍",
        "账号",
        "选课",
        "报到",
    ),
    "orientation": (
        "orientation",
        "arrival",
        "welcome",
        "induction",
        "迎新",
        "orientation",
        "到港",
        "入境",
        "行前",
        "开学",
    ),
    "faq": (
        "faq",
        "frequently asked",
        "question",
        "常见问题",
        "问题",
        "能不能",
        "是否可以",
        "怎么办",
    ),
}


STAGE_TO_PAGE_TYPES: dict[str, tuple[str, ...]] = {
    "offer_acceptance": ("offer_holder", "admitted_student", "faq"),
    "visa": ("visa", "faq"),
    "housing": ("accommodation", "faq"),
    "payment": ("tuition", "faq"),
    "registration": ("registration", "admitted_student", "faq"),
    "orientation": ("orientation", "admitted_student", "faq"),
    "faq": ("faq",),
}


PENDING_ACTIONS: dict[str, tuple[str, ...]] = {
    "offer_acceptance": ("接受", "确认", "缴", "付款", "pay", "accept", "补交"),
    "visa": ("申请", "办理", "递交", "提交", "获批", "apply", "submit", "obtain", "get"),
    "housing": ("申请", "确定", "预订", "apply", "submit", "confirm"),
    "payment": ("缴", "交", "付款", "支付", "pay", "paid"),
    "registration": ("注册", "完成", "激活", "register", "complete"),
    "orientation": ("参加", "报名", "注册", "attend", "join", "register"),
    "faq": ("确认", "解决", "问", "check"),
}


TASK_PLAN_KEYWORDS = (
    "下一步",
    "待办",
    "任务",
    "流程",
    "时间线",
    "清单",
    "计划",
    "做什么",
    "怎么做",
    "准备",
    "todo",
    "checklist",
    "timeline",
    "next step",
)


RISK_KEYWORDS = (
    "风险",
    "截止",
    "deadline",
    "逾期",
    "来不及",
    "late",
    "overdue",
    "错过",
    "urgent",
)


@dataclass(frozen=True)
class IntentResult:
    """Structured routing result shared by all downstream agent modules."""

    intent: str
    stage: str | None
    school: str | None
    page_types: tuple[str, ...]
    confidence: float
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    raw_message: str = ""

    @property
    def needs_task_plan(self) -> bool:
        return self.intent in {"task_plan", "risk_check"}


def normalize_school(value: str | None) -> str | None:
    """Return a canonical school code from English/Chinese aliases."""

    if not value:
        return None

    lowered = value.strip().lower()
    for canonical, aliases in SCHOOL_ALIASES.items():
        if lowered == canonical.lower() or lowered in aliases:
            return canonical

    return None


def detect_school(message: str, default_school: str | None = None) -> str | None:
    text = message.lower()
    entries = sorted(SCHOOL_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
    for canonical, aliases in entries:
        if _contains_alias(text, canonical.lower()):
            return canonical
        if any(_contains_alias(text, alias.lower()) for alias in aliases):
            return canonical
    return normalize_school(default_school) or default_school


def route_intent(message: str, default_school: str | None = None) -> IntentResult:
    """Classify a user message into a small set of workflow intents."""

    text = _compact_text(message)
    school = detect_school(text, default_school)

    stage_scores: dict[str, int] = {}
    matched: list[str] = []
    for stage, keywords in STAGE_KEYWORDS.items():
        hits = _keyword_hits(text, keywords)
        if hits:
            stage_scores[stage] = len(hits)
            matched.extend(hits)

    for stage, boost in _pending_stage_boosts(text).items():
        stage_scores[stage] = stage_scores.get(stage, 0) + boost
        matched.append(f"pending:{stage}")

    stage = _choose_stage(stage_scores)
    page_types = STAGE_TO_PAGE_TYPES.get(stage or "", tuple())

    has_task_trigger = bool(_keyword_hits(text, TASK_PLAN_KEYWORDS))
    has_risk_trigger = bool(_keyword_hits(text, RISK_KEYWORDS))

    if has_risk_trigger:
        intent = "risk_check"
    elif has_task_trigger:
        intent = "task_plan"
    elif stage == "faq":
        intent = "faq"
    elif stage:
        intent = "question_answering"
    else:
        intent = "general_guidance"

    confidence = _confidence(stage_scores, bool(school), has_task_trigger, has_risk_trigger)
    return IntentResult(
        intent=intent,
        stage=stage,
        school=school,
        page_types=page_types,
        confidence=confidence,
        matched_keywords=tuple(dict.fromkeys(matched)),
        raw_message=message,
    )


def infer_completed_flags(message: str) -> set[str]:
    """Infer coarse completed task flags from the user's natural-language state."""

    text = _compact_text(message)
    flags: set[str] = set()

    positive_patterns = {
        "accepted_offer": (
            r"(已经|已|done|completed|accepted).{0,8}(接受|accept).{0,8}(offer|录取)?",
            r"(offer|录取).{0,8}(已经|已).{0,8}(接受|accept)",
        ),
        "paid_deposit": (
            r"(已经|已|paid|交了|缴了).{0,8}(留位费|deposit|押金)",
            r"(留位费|deposit|押金).{0,8}(已经|已|paid|交了|缴了)",
        ),
        "conditions_cleared": (
            r"(已经|已|completed|cleared).{0,8}(conditional|condition|条件|补交|材料)",
            r"(conditional|condition|条件|补交|材料).{0,8}(已经|已).{0,8}(完成|交|清)",
        ),
        "visa_submitted": (
            r"(已经|已|submitted|递交了|提交了|已递交|已提交).{0,8}(签证|visa|entry permit|进入许可)",
            r"(签证|visa|entry permit|进入许可).{0,8}(已经|已).{0,8}(递交|提交|申请)",
        ),
        "visa_approved": (
            r"(签证|visa|entry permit|进入许可).{0,8}(获批|批了|approved|拿到)",
            r"(获批|approved|拿到).{0,8}(签证|visa|entry permit|进入许可)",
        ),
        "housing_applied": (
            r"(已经|已|submitted|申请了|已申请).{0,8}(宿舍|住宿|housing|accommodation)",
            r"(宿舍|住宿|housing|accommodation).{0,8}(已经|已).{0,8}(申请|提交)",
        ),
        "tuition_paid": (
            r"(已经|已|paid|交了|缴了).{0,8}(学费|tuition)",
            r"(学费|tuition).{0,8}(已经|已|paid|交了|缴了)",
        ),
        "registered": (
            r"(已经|已|completed|done|已完成|完成了).{0,8}(注册|registration|enrolment|enrollment)",
            r"(注册|registration|enrolment|enrollment).{0,8}(已经|已|completed|done|已完成|完成了)",
        ),
    }

    for flag, patterns in positive_patterns.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            flags.add(flag)

    return flags


def _compact_text(message: str) -> str:
    return re.sub(r"\s+", " ", message.strip().lower())


def _keyword_hits(text: str, keywords: Iterable[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword.lower() in text]


def _contains_alias(text: str, alias: str) -> bool:
    if re.fullmatch(r"[a-z0-9 ]+", alias):
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return alias in text


def _pending_stage_boosts(text: str) -> dict[str, int]:
    pending_words = ("还没", "尚未", "未", "没有", "没", "not yet", "haven't", "have not")
    boosts: dict[str, int] = {}
    for stage, keywords in STAGE_KEYWORDS.items():
        action_pattern = "|".join(map(re.escape, PENDING_ACTIONS.get(stage, ("完成",))))
        for keyword in keywords:
            escaped = re.escape(keyword.lower())
            if any(
                re.search(rf"{pending}.{{0,10}}{escaped}", text)
                or re.search(
                    rf"{escaped}.{{0,4}}{pending}.{{0,10}}({action_pattern})",
                    text,
                )
                for pending in map(re.escape, pending_words)
            ):
                boosts[stage] = boosts.get(stage, 0) + 4
                break
    return boosts


def _choose_stage(scores: dict[str, int]) -> str | None:
    if not scores:
        return None
    return max(scores.items(), key=lambda item: (item[1], _stage_priority(item[0])))[0]


def _stage_priority(stage: str) -> int:
    priority = {
        "visa": 7,
        "offer_acceptance": 6,
        "registration": 5,
        "payment": 4,
        "housing": 3,
        "orientation": 2,
        "faq": 1,
    }
    return priority.get(stage, 0)


def _confidence(
    stage_scores: dict[str, int],
    has_school: bool,
    has_task_trigger: bool,
    has_risk_trigger: bool,
) -> float:
    score = 0.25
    if stage_scores:
        score += min(0.4, max(stage_scores.values()) * 0.12)
    if has_school:
        score += 0.15
    if has_task_trigger:
        score += 0.1
    if has_risk_trigger:
        score += 0.1
    return round(min(score, 0.95), 2)

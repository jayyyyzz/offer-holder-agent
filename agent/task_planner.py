"""Task planning from student state and official-source entry points."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
import csv
from typing import Mapping

import pandas as pd

from agent.intent_router import IntentResult
from agent.task_state import TaskState


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SCHOOLS_CSV = ROOT_DIR / "data" / "cleaned" / "schools.csv"
DEFAULT_TASKS_CSV = ROOT_DIR / "data" / "cleaned" / "tasks.csv"
DEFAULT_SOURCE_LIST = ROOT_DIR / "source_list.csv"


TASK_COLUMNS = [
    "task_id",
    "school",
    "stage",
    "task_name",
    "description",
    "trigger_condition",
    "deadline",
    "required_documents",
    "action_url",
    "risk_level",
    "source_url",
    "updated_at",
]


STAGE_ORDER = {
    "offer_acceptance": 10,
    "visa": 20,
    "housing": 30,
    "payment": 40,
    "registration": 50,
    "orientation": 60,
}


STAGE_TO_SCHOOL_COLUMN = {
    "offer_acceptance": "offer_holder_url",
    "visa": "visa_url",
    "housing": "accommodation_url",
    "payment": "tuition_url",
    "registration": "admitted_student_url",
    "orientation": "orientation_url",
}


@dataclass(frozen=True)
class StudentProfile:
    """Coarse state supplied by user, command flags, or future onboarding form."""

    school: str | None = None
    program_type: str = "TPG"
    origin: str = "Mainland China"
    completed_flags: set[str] = field(default_factory=set)
    has_conditional_offer: bool | None = None

    def is_completed(self, flag: str) -> bool:
        return flag in self.completed_flags


@dataclass(frozen=True)
class TaskTemplate:
    code: str
    stage: str
    task_name: str
    description: str
    trigger_condition: str
    deadline: str
    required_documents: str
    risk_level: str
    completion_flags: tuple[str, ...]


@dataclass(frozen=True)
class PlannedTask:
    task_id: str
    school: str
    stage: str
    task_name: str
    description: str
    trigger_condition: str
    deadline: str
    required_documents: str
    action_url: str
    risk_level: str
    source_url: str
    updated_at: str
    priority_score: float
    reason: str
    task_code: str = ""
    evidence_count: int = 0
    candidate_evidence_count: int = 0
    usable_evidence_count: int = 0
    review_evidence_count: int = 0
    rejected_evidence_count: int = 0
    evidence_types: str = ""
    official_deadline_evidence: str = ""
    official_document_evidence: str = ""
    official_action_evidence: str = ""
    official_action_urls: str = ""
    official_fee_evidence: str = ""
    evidence_quality_status: str = ""
    evidence_quality_notes: str = ""
    enrichment_status: str = ""
    review_priority: str = ""
    review_reason: str = ""
    review_decision: str = ""
    review_notes: str = ""
    human_review_status: str = ""
    reviewed_at: str = ""
    user_task_status: str = ""
    user_deadline_at: str = ""
    user_deadline_timezone: str = ""
    user_deadline_source: str = ""
    user_reminder_at: str = ""
    user_reminder_status: str = ""
    user_task_notes: str = ""

    def to_csv_row(self) -> dict[str, str]:
        return {column: str(getattr(self, column)) for column in TASK_COLUMNS}


TASK_TEMPLATES: tuple[TaskTemplate, ...] = (
    TaskTemplate(
        code="accept_offer",
        stage="offer_acceptance",
        task_name="接受 offer 并确认入读意向",
        description="登录学校申请系统或 offer letter 指定入口，按要求接受录取。若页面要求同时确认条款、上传回执或选择入学批次，需要一并完成。",
        trigger_condition="收到 offer 后，且尚未完成 official acceptance。",
        deadline="以 offer letter、申请系统或学院邮件显示的 acceptance deadline 为准。",
        required_documents="offer letter；申请系统账号；学校要求的接受录取确认信息。",
        risk_level="high",
        completion_flags=("accepted_offer",),
    ),
    TaskTemplate(
        code="pay_deposit",
        stage="offer_acceptance",
        task_name="缴纳留位费 / admission deposit",
        description="按学校指定付款方式缴纳留位费，并保存付款成功页面、交易编号或银行凭证。",
        trigger_condition="offer 条款或申请系统要求缴纳 deposit，且尚未完成付款。",
        deadline="通常与接受 offer 的截止日绑定；以 offer letter / portal 的金额与截止时间为准。",
        required_documents="银行卡或汇款信息；付款凭证；application number / student ID。",
        risk_level="high",
        completion_flags=("paid_deposit",),
    ),
    TaskTemplate(
        code="submit_conditions",
        stage="offer_acceptance",
        task_name="补交 conditional offer 材料",
        description="核对 conditional offer 中尚未满足的条件，提交最终成绩单、毕业证、学位证、语言成绩或官方认证文件。",
        trigger_condition="offer 为 conditional，且仍有 pending condition。",
        deadline="以 conditional offer、学院邮件或学校系统内的 document deadline 为准。",
        required_documents="最终成绩单；毕业证 / 学位证；语言成绩；官方认证件；学校额外要求文件。",
        risk_level="high",
        completion_flags=("conditions_cleared",),
    ),
    TaskTemplate(
        code="apply_student_visa",
        stage="visa",
        task_name="申请学生签证 / 进入许可",
        description="内地学生通常需要通过学校申请 entry permit / student visa。尽早准备表格、身份证明、录取证明和资金材料，等待学校或入境处处理。",
        trigger_condition="决定入读且尚未递交学生签证 / 进入许可申请。",
        deadline="以学校签证页面、邮件及香港入境事务处处理周期为准；不要等到临近开学才递交。",
        required_documents="签证 / 进入许可申请表；旅行证件；录取证明；财力证明；照片；学校要求的其他文件。",
        risk_level="high",
        completion_flags=("visa_submitted", "visa_approved"),
    ),
    TaskTemplate(
        code="apply_accommodation",
        stage="housing",
        task_name="申请宿舍或安排校外住宿",
        description="查询学校住宿申请窗口、资格和优先级；如校内宿舍名额有限，同时准备校外租房备选方案。",
        trigger_condition="计划到港就读，且尚未提交住宿申请或确定住所。",
        deadline="以学校住宿页面公布的 application period / hall application deadline 为准。",
        required_documents="student ID / application number；入学证明；住宿申请表；可能需要的紧急联系人信息。",
        risk_level="medium",
        completion_flags=("housing_applied",),
    ),
    TaskTemplate(
        code="pay_tuition",
        stage="payment",
        task_name="核对并缴纳学费 / 其他费用",
        description="核对 programme tuition、缴费方式、分期安排和账单生成时间，按学校财务或学生系统要求付款。",
        trigger_condition="学费账单或缴费通知已发布，且尚未完成付款。",
        deadline="以学校缴费页面、学生系统账单或学院邮件为准。",
        required_documents="student ID；缴费通知；付款工具；付款凭证。",
        risk_level="medium",
        completion_flags=("tuition_paid",),
    ),
    TaskTemplate(
        code="complete_registration",
        stage="registration",
        task_name="完成线上注册 / 学籍激活",
        description="按学校注册指引激活学生账号、完成个人资料、上传证件或注册确认，并检查是否需要线下核验。",
        trigger_condition="学校开放 registration / enrolment，且尚未完成。",
        deadline="以学校 registration guide、学生系统和邮件通知为准。",
        required_documents="身份证明；旅行证件；证件照片；录取信息；学校要求上传的声明或表格。",
        risk_level="high",
        completion_flags=("registered",),
    ),
    TaskTemplate(
        code="prepare_arrival_orientation",
        stage="orientation",
        task_name="准备入境与参加 orientation",
        description="整理入境文件、住宿安排、交通和报到材料，关注 orientation / induction 活动报名与时间表。",
        trigger_condition="签证 / 进入许可获批后，或开学前学校发布 orientation 安排。",
        deadline="以学校 orientation 页面、学院邮件和入境日期安排为准。",
        required_documents="旅行证件；签证 / 进入许可；录取证明；住宿地址；保险 / 现金 / 电话卡等到港准备材料。",
        risk_level="medium",
        completion_flags=("orientation_done",),
    ),
)


TASK_CODE_COMPLETION_FLAGS = {
    "accept_offer": ("accepted_offer",),
    "pay_deposit": ("paid_deposit",),
    "submit_conditions": ("conditions_cleared",),
    "apply_student_visa": ("visa_submitted", "visa_approved"),
    "apply_accommodation": ("housing_applied",),
    "pay_tuition": ("tuition_paid",),
    "complete_registration": ("registered",),
    "prepare_arrival_orientation": ("orientation_done",),
}


class TaskPlanner:
    """Generate a prioritized task list for one student state."""

    def __init__(
        self,
        schools_csv: Path | str = DEFAULT_SCHOOLS_CSV,
        tasks_csv: Path | str = DEFAULT_TASKS_CSV,
        source_list: Path | str = DEFAULT_SOURCE_LIST,
        task_source_csv: Path | str | None = None,
    ) -> None:
        self.schools_csv = Path(schools_csv)
        self.tasks_csv = Path(tasks_csv)
        self.source_list = Path(source_list)
        self.task_source_csv = Path(task_source_csv) if task_source_csv else None
        self._school_urls = load_school_urls(self.schools_csv, self.source_list)

    def plan(
        self,
        profile: StudentProfile,
        *,
        intent: IntentResult | None = None,
        limit: int = 6,
        task_states: Mapping[str, TaskState] | None = None,
    ) -> list[PlannedTask]:
        if self.task_source_csv:
            return self._plan_from_csv(
                profile,
                intent=intent,
                limit=limit,
                task_states=task_states,
            )

        schools = [profile.school] if profile.school else sorted(self._school_urls)
        candidates: list[PlannedTask] = []

        for school in schools:
            if not school:
                continue
            for template in TASK_TEMPLATES:
                include_unknown_condition = (intent is None) or (intent.stage == "offer_acceptance")
                if not should_include_template(
                    template,
                    profile,
                    include_unknown_condition=include_unknown_condition,
                ):
                    continue
                task = build_task(
                    template,
                    school=school,
                    url_catalog=self._school_urls.get(school, {}),
                    profile=profile,
                    intent=intent,
                )
                task = apply_task_state(task, task_states)
                if task:
                    candidates.append(task)

        candidates.sort(key=lambda task: (-task.priority_score, STAGE_ORDER.get(task.stage, 99)))
        return candidates[:limit]

    def _plan_from_csv(
        self,
        profile: StudentProfile,
        *,
        intent: IntentResult | None,
        limit: int,
        task_states: Mapping[str, TaskState] | None = None,
    ) -> list[PlannedTask]:
        if not self.task_source_csv or not self.task_source_csv.exists():
            raise FileNotFoundError(f"task source csv not found: {self.task_source_csv}")

        frame = pd.read_csv(self.task_source_csv, dtype=str, keep_default_na=False)
        required = set(TASK_COLUMNS)
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"task source csv missing required columns: {', '.join(missing)}")

        schools = {profile.school.lower()} if profile.school else None
        candidates: list[PlannedTask] = []
        for row in frame.to_dict(orient="records"):
            school = str(row.get("school", ""))
            if schools and school.lower() not in schools:
                continue

            task_code = infer_task_code_from_row(row)
            include_unknown_condition = (intent is None) or (intent.stage == "offer_acceptance")
            if not should_include_task_code(
                task_code,
                profile,
                include_unknown_condition=include_unknown_condition,
            ):
                continue

            task = build_task_from_csv_row(row, task_code=task_code, profile=profile, intent=intent)
            task = apply_task_state(task, task_states)
            if task:
                candidates.append(task)

        candidates.sort(key=lambda task: (-task.priority_score, STAGE_ORDER.get(task.stage, 99)))
        return candidates[:limit]

    def export_seed_tasks(self, output_path: Path | str | None = None) -> list[PlannedTask]:
        output = Path(output_path) if output_path else self.tasks_csv
        tasks: list[PlannedTask] = []
        for school in sorted(self._school_urls):
            profile = StudentProfile(school=school)
            for template in TASK_TEMPLATES:
                if not should_include_template(
                    template,
                    profile,
                    include_unknown_condition=True,
                ):
                    continue
                tasks.append(
                    build_task(
                        template,
                        school=school,
                        url_catalog=self._school_urls.get(school, {}),
                        profile=profile,
                        intent=None,
                    )
                )

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=TASK_COLUMNS)
            writer.writeheader()
            for task in tasks:
                writer.writerow(task.to_csv_row())
        return tasks


def load_school_urls(
    schools_csv: Path | str = DEFAULT_SCHOOLS_CSV,
    source_list: Path | str = DEFAULT_SOURCE_LIST,
) -> dict[str, dict[str, str]]:
    urls: dict[str, dict[str, str]] = {}

    schools_path = Path(schools_csv)
    if schools_path.exists():
        frame = pd.read_csv(schools_path, dtype=str, keep_default_na=False)
        for row in frame.to_dict(orient="records"):
            school = _canonical_school(row.get("school_id") or row.get("school_name", ""))
            urls.setdefault(school, {})
            for stage, column in STAGE_TO_SCHOOL_COLUMN.items():
                urls[school][stage] = row.get(column, "")
            urls[school]["official_website"] = row.get("official_website", "")

    source_path = Path(source_list)
    if source_path.exists():
        frame = pd.read_csv(source_path, dtype=str, keep_default_na=False)
        for row in frame.to_dict(orient="records"):
            school = _canonical_school(row.get("school", ""))
            page_type = row.get("page_type", "")
            stage = row.get("stage", "")
            url = row.get("url", "")
            urls.setdefault(school, {})
            if page_type:
                urls[school][page_type] = url
            if stage:
                urls[school].setdefault(stage, url)

    return urls


def should_include_template(
    template: TaskTemplate,
    profile: StudentProfile,
    *,
    include_unknown_condition: bool = False,
) -> bool:
    if any(flag in profile.completed_flags for flag in template.completion_flags):
        return False

    if template.code == "submit_conditions":
        if profile.has_conditional_offer is True:
            return True
        if profile.has_conditional_offer is False:
            return False
        return include_unknown_condition

    return True


def should_include_task_code(
    task_code: str,
    profile: StudentProfile,
    *,
    include_unknown_condition: bool = False,
) -> bool:
    completion_flags = TASK_CODE_COMPLETION_FLAGS.get(task_code, ())
    if any(flag in profile.completed_flags for flag in completion_flags):
        return False

    if task_code == "submit_conditions":
        if profile.has_conditional_offer is True:
            return True
        if profile.has_conditional_offer is False:
            return False
        return include_unknown_condition

    return True


def build_task(
    template: TaskTemplate,
    *,
    school: str,
    url_catalog: dict[str, str],
    profile: StudentProfile,
    intent: IntentResult | None,
) -> PlannedTask:
    action_url = choose_action_url(template, url_catalog)
    score, reason = priority_score(template, profile=profile, intent=intent)

    return PlannedTask(
        task_id=f"{school.lower()}-{template.code}",
        school=school,
        stage=template.stage,
        task_name=template.task_name,
        description=template.description,
        trigger_condition=template.trigger_condition,
        deadline=template.deadline,
        required_documents=template.required_documents,
        action_url=action_url,
        risk_level=template.risk_level,
        source_url=action_url,
        updated_at=datetime.now(UTC).date().isoformat(),
        priority_score=score,
        reason=reason,
        task_code=template.code,
    )


def build_task_from_csv_row(
    row: dict[str, object],
    *,
    task_code: str,
    profile: StudentProfile,
    intent: IntentResult | None,
) -> PlannedTask:
    template = TaskTemplate(
        code=task_code,
        stage=str(row.get("stage", "")),
        task_name=str(row.get("task_name", "")),
        description=str(row.get("description", "")),
        trigger_condition=str(row.get("trigger_condition", "")),
        deadline=str(row.get("deadline", "")),
        required_documents=str(row.get("required_documents", "")),
        risk_level=str(row.get("risk_level", "")) or "medium",
        completion_flags=TASK_CODE_COMPLETION_FLAGS.get(task_code, ()),
    )
    score, reason = priority_score(template, profile=profile, intent=intent)
    evidence_count = _to_int(row.get("evidence_count", 0))
    candidate_evidence_count = _to_int(row.get("candidate_evidence_count", evidence_count))
    usable_evidence_count = _to_int(row.get("usable_evidence_count", evidence_count))
    review_evidence_count = _to_int(row.get("review_evidence_count", 0))
    rejected_evidence_count = _to_int(row.get("rejected_evidence_count", 0))
    enrichment_status = str(row.get("enrichment_status", ""))
    if evidence_count:
        reason = f"{reason}；已匹配 {evidence_count} 条官方证据候选，需以原文复核为准"
    if review_evidence_count or rejected_evidence_count:
        reason = (
            f"{reason}；质量审计：{usable_evidence_count} 条可用，"
            f"{review_evidence_count} 条待复核，{rejected_evidence_count} 条已排除"
        )
    elif enrichment_status:
        reason = f"{reason}；当前增强任务表状态：{enrichment_status}"

    action_url = str(row.get("action_url", ""))
    official_action_urls = str(row.get("official_action_urls", ""))
    if not action_url and official_action_urls:
        action_url = official_action_urls.split("|", 1)[0].strip()

    return PlannedTask(
        task_id=str(row.get("task_id", "")),
        school=str(row.get("school", "")),
        stage=template.stage,
        task_name=template.task_name,
        description=template.description,
        trigger_condition=template.trigger_condition,
        deadline=template.deadline,
        required_documents=template.required_documents,
        action_url=action_url,
        risk_level=template.risk_level,
        source_url=str(row.get("source_url", "")) or action_url,
        updated_at=str(row.get("updated_at", "")) or datetime.now(UTC).date().isoformat(),
        priority_score=score,
        reason=reason,
        task_code=task_code,
        evidence_count=evidence_count,
        candidate_evidence_count=candidate_evidence_count,
        usable_evidence_count=usable_evidence_count,
        review_evidence_count=review_evidence_count,
        rejected_evidence_count=rejected_evidence_count,
        evidence_types=str(row.get("evidence_types", "")),
        official_deadline_evidence=str(row.get("official_deadline_evidence", "")),
        official_document_evidence=str(row.get("official_document_evidence", "")),
        official_action_evidence=str(row.get("official_action_evidence", "")),
        official_action_urls=official_action_urls,
        official_fee_evidence=str(row.get("official_fee_evidence", "")),
        evidence_quality_status=str(row.get("evidence_quality_status", "")),
        evidence_quality_notes=str(row.get("evidence_quality_notes", "")),
        enrichment_status=enrichment_status,
        review_priority=str(row.get("review_priority", "")),
        review_reason=str(row.get("review_reason", "")),
        review_decision=str(row.get("review_decision", "")),
        review_notes=str(row.get("review_notes", "")),
        human_review_status=str(row.get("human_review_status", "")),
        reviewed_at=str(row.get("reviewed_at", "")),
    )


def apply_task_state(
    task: PlannedTask,
    task_states: Mapping[str, TaskState] | None,
) -> PlannedTask | None:
    if not task_states:
        return task

    state = task_states.get(task.task_id) or task_states.get(task.task_code)
    if not state:
        return task

    if state.status in {"done", "skipped"}:
        return None

    score = task.priority_score
    reasons = [task.reason]
    if state.status:
        reasons.append(f"个人任务状态：{state.status}")
    if state.deadline_at:
        score += 8.0
        deadline_label = state.deadline_at
        if state.deadline_timezone:
            deadline_label = f"{deadline_label} {state.deadline_timezone}"
        reasons.append(f"已记录个人截止时间：{deadline_label}")
    if state.reminder_at:
        reasons.append(f"已记录提醒时间：{state.reminder_at}")

    return replace(
        task,
        priority_score=round(score, 2),
        reason="；".join(reason for reason in reasons if reason),
        user_task_status=state.status,
        user_deadline_at=state.deadline_at,
        user_deadline_timezone=state.deadline_timezone,
        user_deadline_source=state.deadline_source,
        user_reminder_at=state.reminder_at,
        user_reminder_status=state.reminder_status,
        user_task_notes=state.notes,
    )


def infer_task_code_from_row(row: dict[str, object]) -> str:
    task_code = str(row.get("task_code", "")).strip()
    if task_code:
        return task_code

    task_id = str(row.get("task_id", "")).strip()
    if "-" in task_id:
        return task_id.split("-", 1)[1]

    name = " ".join(str(row.get(field, "")) for field in ("task_name", "description")).lower()
    if "visa" in name or "签证" in name or "進入許可" in name or "进入许可" in name:
        return "apply_student_visa"
    if "deposit" in name or "留位费" in name or "留位費" in name:
        return "pay_deposit"
    if "accept" in name or "接受" in name:
        return "accept_offer"
    if "conditional" in name or "补交" in name or "補交" in name:
        return "submit_conditions"
    if "accommodation" in name or "housing" in name or "宿舍" in name:
        return "apply_accommodation"
    if "tuition" in name or "学费" in name or "學費" in name:
        return "pay_tuition"
    if "registration" in name or "注册" in name or "註冊" in name:
        return "complete_registration"
    if "orientation" in name or "arrival" in name or "迎新" in name:
        return "prepare_arrival_orientation"
    return ""


def choose_action_url(template: TaskTemplate, url_catalog: dict[str, str]) -> str:
    if template.code == "pay_deposit":
        return url_catalog.get("offer_holder") or url_catalog.get("offer_acceptance", "")
    if template.code == "submit_conditions":
        return url_catalog.get("admitted_student") or url_catalog.get("offer_holder", "")
    if template.code == "complete_registration":
        return url_catalog.get("registration") or url_catalog.get("registration_url", "") or (
            url_catalog.get("admitted_student", "")
        )
    if template.code == "prepare_arrival_orientation":
        return url_catalog.get("orientation") or url_catalog.get("admitted_student", "")

    return (
        url_catalog.get(template.stage)
        or url_catalog.get(
            {
                "visa": "visa",
                "housing": "accommodation",
                "payment": "tuition",
                "offer_acceptance": "offer_holder",
            }.get(template.stage, ""),
            "",
        )
        or url_catalog.get("official_website", "")
    )


def priority_score(
    template: TaskTemplate,
    *,
    profile: StudentProfile,
    intent: IntentResult | None,
) -> tuple[float, str]:
    risk_base = {"high": 50.0, "medium": 30.0, "low": 15.0}.get(template.risk_level, 20.0)
    order_bonus = max(0.0, 25.0 - STAGE_ORDER.get(template.stage, 99) / 4)
    score = risk_base + order_bonus
    reasons: list[str] = []

    if template.risk_level == "high":
        reasons.append("高风险事项，通常会影响入学资格或报到")

    if intent and intent.stage == template.stage:
        score += 35.0
        reasons.append("与你当前提问阶段直接相关")

    if template.code == "apply_student_visa" and profile.origin.lower().startswith("mainland"):
        score += 12.0
        reasons.append("内地学生通常需要办理进入许可 / 学生签证")

    if template.code == "pay_deposit" and profile.is_completed("accepted_offer"):
        score += 10.0
        reasons.append("已接受 offer 后，留位费通常是紧接着要确认的事项")

    if template.code == "apply_student_visa" and profile.is_completed("paid_deposit"):
        score += 8.0
        reasons.append("已完成留位费后，应尽早推进签证")

    if template.code == "prepare_arrival_orientation" and not profile.is_completed("visa_approved"):
        score -= 20.0
        reasons.append("通常等签证 / 进入许可明确后再细化到港安排")

    if not reasons:
        reasons.append("按 Offer 后入学准备流程排序")

    return round(score, 2), "；".join(reasons)


def _canonical_school(value: str) -> str:
    normalized = value.strip().lower()
    mapping = {
        "hku": "HKU",
        "the university of hong kong": "HKU",
        "cuhk": "CUHK",
        "the chinese university of hong kong": "CUHK",
        "hkust": "HKUST",
        "the hong kong university of science and technology": "HKUST",
        "cityu": "CityU",
        "city university of hong kong": "CityU",
        "polyu": "PolyU",
        "the hong kong polytechnic university": "PolyU",
        "hkbu": "HKBU",
        "hong kong baptist university": "HKBU",
        "lingnan": "Lingnan",
        "lingnan university": "Lingnan",
        "eduhk": "EdUHK",
        "the education university of hong kong": "EdUHK",
    }
    return mapping.get(normalized, value.strip())


def _to_int(value: object) -> int:
    try:
        if value == "":
            return 0
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0

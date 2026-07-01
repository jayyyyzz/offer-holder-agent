"""CLI for the initial HK offer-holder preparation agent."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent.intent_router import infer_completed_flags, normalize_school, route_intent
from agent.llm_prompt import DEFAULT_LLM_PROMPT_PATH, build_grounded_prompt, write_grounded_prompt
from agent.openai_responses import (
    DEFAULT_OPENAI_API_KEY_ENV,
    DEFAULT_OPENAI_MODEL,
    generate_grounded_response,
    write_openai_run_metadata,
)
from agent.rag_retriever import DEFAULT_CHUNKS_CSV, DEFAULT_RAW_DIR, LocalRagRetriever, RetrievalResult
from agent.response_generator import ensure_source_citations, format_agent_response
from agent.risk_checker import RiskChecker
from agent.task_planner import DEFAULT_TASKS_CSV, StudentProfile, TaskPlanner
from agent.task_state import (
    DEFAULT_USER_TASK_STATE_CSV,
    TaskState,
    VALID_REMINDER_STATUSES,
    VALID_STATUSES,
    load_user_task_states,
    upsert_user_task_state,
)
from agent.user_state import (
    DEFAULT_USER_STATE_CSV,
    load_user_profile,
    merge_profiles,
    save_user_profile,
)
from crawler.crawl_pages import DEFAULT_LOG_PATH, DEFAULT_SOURCE_LIST
from crawler.summarize_crawl import (
    DEFAULT_SUMMARY_PATH,
    build_crawl_summary,
    write_crawl_summary,
)
from knowledge_base.audit_data_quality import (
    DEFAULT_QUALITY_REPORT,
    build_quality_report,
    write_quality_report,
)
from knowledge_base.audit_task_evidence_quality import (
    DEFAULT_TASK_EVIDENCE_QUALITY_REPORT,
    build_task_evidence_quality_report,
    write_task_evidence_quality_report,
)
from knowledge_base.clean_faq import (
    DEFAULT_CLEAN_FAQ_CSV,
    DEFAULT_FAQ_QUALITY_REPORT,
    clean_faq_candidates,
    write_clean_faq,
    write_quality_report as write_faq_quality_report,
)
from knowledge_base.extract_faq import DEFAULT_FAQ_CSV, extract_faq_items, write_faq_csv
from knowledge_base.extract_task_evidence import (
    DEFAULT_TASK_EVIDENCE_CSV,
    extract_task_evidence,
    write_task_evidence_csv,
)
from knowledge_base.enrich_tasks import (
    DEFAULT_TASKS_ENRICHED_CSV,
    build_enriched_tasks,
    write_enriched_tasks,
)
from knowledge_base.phase1_outputs import (
    DEFAULT_PHASE1_MANIFEST,
    DEFAULT_RAW_PAGE_INDEX,
    DEFAULT_SCHEMA_DICTIONARY,
    write_phase1_outputs,
)
from knowledge_base.review_enriched_tasks import (
    DEFAULT_TASK_REVIEW_REPORT,
    build_task_review_report,
    write_task_review_report,
)
from knowledge_base.reviewed_tasks import (
    DEFAULT_TASK_REVIEW_DECISIONS_CSV,
    DEFAULT_TASK_REVIEW_PENDING_EXPORT_CSV,
    DEFAULT_TASK_REVIEW_SUMMARY_CSV,
    DEFAULT_TASKS_REVIEWED_CSV,
    build_review_pending_export,
    build_review_pending_summary,
    build_reviewed_tasks,
    init_task_review_decisions,
    write_reviewed_tasks,
    write_task_review_decisions,
    write_task_review_pending_export,
    write_task_review_summary,
)
from knowledge_base.vector_index import (
    DEFAULT_VECTOR_INDEX_CSV,
    build_vector_index,
    search_vector_index,
    write_vector_index,
)


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    args = build_parser().parse_args(argv)

    if args.list_user_tasks:
        print(render_user_task_dashboard(args))
        return 0

    if args.list_task_reminders:
        print(render_user_task_reminders(args))
        return 0

    if args.list_task_agenda:
        print(render_user_task_agenda(args))
        return 0

    if args.build_kb:
        retriever = LocalRagRetriever(raw_dir=args.raw_dir, chunks_csv=args.chunks_csv)
        faq_csv = args.clean_faq_csv if args.clean_faq_csv.exists() else None
        chunks = retriever.export_chunks(args.chunks_csv, faq_csv=faq_csv)
        print(f"已构建 knowledge base chunks：{len(chunks)} 条 -> {args.chunks_csv}")
        return 0

    if args.export_seed_tasks:
        planner = TaskPlanner()
        tasks = planner.export_seed_tasks()
        print(f"已导出初始任务模板：{len(tasks)} 条 -> data/cleaned/tasks.csv")
        return 0

    if args.extract_faq:
        school_filter = {school.lower() for school in args.school_filter} if args.school_filter else None
        items = extract_faq_items(
            args.raw_dir,
            include_all_pages=args.all_pages,
            school_filter=school_filter,
            min_answer_chars=args.min_answer_chars,
        )
        write_faq_csv(items, args.faq_csv)
        print(f"已抽取 FAQ 候选：{len(items)} 条 -> {args.faq_csv}")
        return 0

    if args.summarize_crawl:
        frame = build_crawl_summary(args.source_list, args.log_path)
        write_crawl_summary(frame, args.crawl_summary_csv)
        attention_count = int((frame["needs_attention"] == "yes").sum())
        print(f"已生成 crawl summary：{len(frame)} 条 -> {args.crawl_summary_csv}")
        print(frame["latest_status"].value_counts(dropna=False).to_string())
        print(f"needs_attention: {attention_count}")
        return 0

    if args.audit_data:
        summary_frame = build_crawl_summary(args.source_list, args.log_path)
        write_crawl_summary(summary_frame, args.crawl_summary_csv)
        frame = build_quality_report(
            summary_path=args.crawl_summary_csv,
            chunks_csv=args.chunks_csv,
            faq_csv=args.faq_csv,
            tasks_csv=args.tasks_csv,
        )
        write_quality_report(frame, args.quality_report_csv)
        attention_count = int((frame["needs_attention"] == "yes").sum())
        print(f"已生成 data quality report：{len(frame)} 条 -> {args.quality_report_csv}")
        print(frame["coverage_level"].value_counts(dropna=False).to_string())
        print(f"needs_attention: {attention_count}")
        return 0

    if args.clean_faq:
        cleaned_rows, quality_rows = clean_faq_candidates(args.faq_csv, min_score=args.min_faq_score)
        write_clean_faq(cleaned_rows, args.clean_faq_csv)
        write_faq_quality_report(quality_rows, args.faq_quality_report_csv)
        print(f"已生成 cleaned FAQ：{len(cleaned_rows)} 条 -> {args.clean_faq_csv}")
        print(f"已生成 FAQ quality report：{len(quality_rows)} 条 -> {args.faq_quality_report_csv}")
        return 0

    if args.extract_task_evidence:
        evidence = extract_task_evidence(
            args.clean_faq_csv,
            max_per_question=args.max_task_evidence_per_question,
        )
        write_task_evidence_csv(evidence, args.task_evidence_csv)
        print(f"已生成 task evidence：{len(evidence)} 条 -> {args.task_evidence_csv}")
        return 0

    if args.audit_task_evidence_quality:
        frame = build_task_evidence_quality_report(
            task_evidence_csv=args.task_evidence_csv,
            source_list=args.source_list,
        )
        write_task_evidence_quality_report(frame, args.task_evidence_quality_csv)
        print(f"已生成 task evidence quality report：{len(frame)} 条 -> {args.task_evidence_quality_csv}")
        if not frame.empty:
            print(frame["quality_decision"].value_counts(dropna=False).to_string())
        return 0

    if args.prepare_phase1_outputs:
        counts = write_phase1_outputs(
            raw_dir=args.raw_dir,
            raw_page_index=args.raw_page_index_csv,
            phase1_manifest=args.phase1_manifest_csv,
            schema_dictionary=args.schema_dictionary_csv,
        )
        print(
            "已生成 Phase 1 归档元数据："
            f"raw_page_index={counts['raw_page_index_rows']} 行，"
            f"schema_dictionary={counts['schema_dictionary_rows']} 行，"
            f"phase1_manifest={counts['phase1_manifest_rows']} 行"
        )
        return 0

    if args.enrich_tasks:
        task_evidence_quality_csv = (
            args.task_evidence_quality_csv if args.task_evidence_quality_csv.exists() else None
        )
        frame = build_enriched_tasks(
            args.tasks_csv,
            args.task_evidence_csv,
            task_evidence_quality_csv,
            max_items_per_field=args.max_evidence_items_per_field,
        )
        write_enriched_tasks(frame, args.tasks_enriched_csv)
        found = int((frame["enrichment_status"] == "evidence_found").sum()) if not frame.empty else 0
        print(
            f"已生成 tasks_enriched：{len(frame)} 条 -> {args.tasks_enriched_csv}，"
            f"其中 {found} 条匹配到任务证据"
        )
        return 0

    if args.review_enriched_tasks:
        frame = build_task_review_report(args.tasks_enriched_csv)
        write_task_review_report(frame, args.task_review_report_csv)
        print(f"已生成 tasks_enriched review report：{len(frame)} 条 -> {args.task_review_report_csv}")
        return 0

    if args.init_task_review_decisions:
        frame = init_task_review_decisions(
            args.task_review_report_csv,
            task_review_decisions_csv=args.task_review_decisions_csv if args.task_review_decisions_csv.exists() else None,
            school_filter=args.review_school,
            pending_only=args.review_pending_only,
        )
        write_task_review_decisions(frame, args.task_review_decisions_csv)
        print(f"已生成 task review decisions：{len(frame)} 条 -> {args.task_review_decisions_csv}")
        return 0

    if args.build_reviewed_tasks:
        frame = build_reviewed_tasks(
            args.tasks_enriched_csv,
            args.task_review_report_csv,
            args.task_review_decisions_csv if args.task_review_decisions_csv.exists() else None,
            school_filter=args.review_school,
            pending_only=args.review_pending_only,
        )
        write_reviewed_tasks(frame, args.tasks_reviewed_csv)
        print(f"已生成 tasks_reviewed：{len(frame)} 条 -> {args.tasks_reviewed_csv}")
        return 0

    if args.review_pending_summary:
        frame = build_review_pending_summary(
            args.task_review_report_csv,
            args.task_review_decisions_csv if args.task_review_decisions_csv.exists() else None,
            school_filter=args.review_school,
        )
        if args.task_review_summary_csv:
            write_task_review_summary(frame, args.task_review_summary_csv)
            print(f"已生成 review pending summary：{len(frame)} 条 -> {args.task_review_summary_csv}")
        if frame.empty:
            print("当前没有待审摘要可输出。")
        else:
            print(frame.to_string(index=False))
        return 0

    if args.review_pending_export:
        frame = build_review_pending_export(
            args.task_review_report_csv,
            args.task_review_decisions_csv if args.task_review_decisions_csv.exists() else None,
            school_filter=args.review_school,
        )
        write_task_review_pending_export(frame, args.task_review_pending_export_csv)
        print(f"已生成 review pending export：{len(frame)} 条 -> {args.task_review_pending_export_csv}")
        if frame.empty:
            print("当前没有待审任务可导出。")
        else:
            print(frame.to_string(index=False))
        return 0

    if args.build_vector_index:
        frame = build_vector_index(
            args.chunks_csv,
            backend=args.vector_backend,
            max_terms=args.vector_max_terms,
            chroma_dir=args.chroma_dir,
            collection_name=args.chroma_collection_name,
            embedding_provider=args.embedding_provider,
            embedding_dimensions=args.embedding_dimensions,
            openai_api_key_env=args.openai_api_key_env,
            openai_embedding_model=args.openai_embedding_model,
        )
        write_vector_index(frame, args.vector_index_csv)
        if args.vector_backend == "sparse":
            print(f"已生成本地 sparse vector index：{len(frame)} 条 -> {args.vector_index_csv}")
        else:
            print(f"已生成 Chroma vector index：{args.chroma_collection_name} -> {args.chroma_dir}")
        return 0

    if args.set_task_status or args.deadline_at or args.reminder_at:
        if not args.user_id:
            raise SystemExit("更新任务状态时需要提供 --user-id。")
        if not args.task_id and not args.task_code:
            raise SystemExit("更新任务状态时需要提供 --task-id 或 --task-code。")
        task_id = args.task_id or (
            f"{(normalize_school(args.school) or args.school or '').lower()}-{args.task_code}"
            if args.task_code and args.school
            else ""
        )
        state = upsert_user_task_state(
            user_id=args.user_id,
            path=args.task_state_csv,
            school=normalize_school(args.school) or args.school or "",
            task_id=task_id,
            task_code=args.task_code or "",
            stage=args.task_stage or "",
            status=args.set_task_status or "",
            deadline_at=args.deadline_at or "",
            deadline_timezone=args.deadline_timezone or "",
            deadline_source=args.deadline_source or "",
            deadline_source_ref=args.deadline_source_ref or "",
            reminder_at=args.reminder_at or "",
            reminder_timezone=args.reminder_timezone or "",
            reminder_status=args.reminder_status or "",
            notes=args.task_state_notes or "",
        )
        print(f"已更新用户任务状态：{state.user_id} / {state.task_id or state.task_code}")
        if not args.message and not args.interactive:
            return 0

    if args.interactive:
        return run_interactive(args)

    if not args.message:
        raise SystemExit("请提供 --message，或使用 --interactive 进入交互模式。")

    response = run_once(args, args.message)
    print(response)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initial offer-holder preparation agent backed by local official-page archive.",
    )
    parser.add_argument("--message", "-m", help="用户问题或状态描述，例如：我已交留位费，还没申请签证，下一步做什么？")
    parser.add_argument("--school", help="学校代码，例如 HKU / CUHK / HKUST / CityU / PolyU / HKBU / Lingnan / EdUHK")
    parser.add_argument("--origin", default="Mainland China", help="学生来源地，默认 Mainland China")
    parser.add_argument("--program-type", default="TPG", help="项目类型，默认 TPG")
    parser.add_argument("--has-conditional", action="store_true", help="标记为 conditional offer")
    parser.add_argument("--no-conditional", action="store_true", help="标记为非 conditional offer")
    parser.add_argument("--accepted-offer", action="store_true", help="已接受 offer")
    parser.add_argument("--paid-deposit", action="store_true", help="已缴纳留位费")
    parser.add_argument("--conditions-cleared", action="store_true", help="已满足 conditional offer 条件")
    parser.add_argument("--visa-submitted", action="store_true", help="已递交签证 / 进入许可")
    parser.add_argument("--visa-approved", action="store_true", help="签证 / 进入许可已获批")
    parser.add_argument("--housing-applied", action="store_true", help="已申请宿舍或确定住宿")
    parser.add_argument("--tuition-paid", action="store_true", help="已缴纳学费")
    parser.add_argument("--registered", action="store_true", help="已完成注册")
    parser.add_argument("--user-id", help="本地用户状态 ID，例如 email hash、微信备注名或自定义代号")
    parser.add_argument("--load-user-state", action="store_true", help="按 --user-id 从 user_states.csv 读取用户状态")
    parser.add_argument("--save-user-state", action="store_true", help="本次问答后把用户状态保存到 user_states.csv")
    parser.add_argument("--state-notes", default="", help="保存用户状态时附加备注")
    parser.add_argument("--task-state-csv", type=Path, default=DEFAULT_USER_TASK_STATE_CSV)
    parser.add_argument("--load-task-state", action="store_true", help="按 --user-id 从 user_task_states.csv 读取单任务状态")
    parser.add_argument("--list-user-tasks", action="store_true", help="输出某个用户的个性化任务清单，需要 --user-id")
    parser.add_argument("--list-task-reminders", action="store_true", help="输出某个用户已记录的 deadline / reminder 清单，需要 --user-id")
    parser.add_argument("--list-task-agenda", action="store_true", help="输出某个用户今日/近期需要处理的任务视图，需要 --user-id")
    parser.add_argument("--set-task-status", choices=sorted(VALID_STATUSES - {""}), help="更新某个用户任务的状态")
    parser.add_argument("--task-id", help="用户任务状态对应的 task_id")
    parser.add_argument("--task-code", help="用户任务状态对应的 task_code，例如 apply_student_visa")
    parser.add_argument("--task-stage", help="用户任务状态对应的阶段，例如 visa")
    parser.add_argument("--deadline-at", help="用户确认过的个人截止时间，YYYY-MM-DD 或 ISO datetime")
    parser.add_argument("--deadline-timezone", default="", help="个人截止时间时区，例如 Asia/Hong_Kong")
    parser.add_argument("--deadline-source", default="", help="个人截止时间来源，例如 portal / offer_letter / school_email")
    parser.add_argument("--deadline-source-ref", default="", help="个人截止时间来源备注或 URL")
    parser.add_argument("--reminder-at", help="提醒时间，ISO datetime")
    parser.add_argument("--reminder-timezone", default="", help="提醒时间时区")
    parser.add_argument("--reminder-status", choices=sorted(VALID_REMINDER_STATUSES - {""}), default="", help="提醒状态")
    parser.add_argument("--task-state-notes", default="", help="保存用户任务状态时附加备注")
    parser.add_argument("--status-filter", action="append", choices=sorted(VALID_STATUSES - {""}), help="列任务或提醒时按状态筛选；可重复")
    parser.add_argument("--include-completed-tasks", action="store_true", help="列任务或提醒时包含 done / skipped")
    parser.add_argument("--agenda-date", help="生成 agenda 视图时使用的基准日期，YYYY-MM-DD；默认取当前日期")
    parser.add_argument("--agenda-days", type=int, default=7, help="agenda 视图向后看多少天，默认 7")
    parser.add_argument("--agenda-timezone", default="Asia/Hong_Kong", help="agenda 视图使用的时区，默认 Asia/Hong_Kong")
    parser.add_argument("--top-k", type=int, default=5, help="检索官方依据片段数量")
    parser.add_argument("--task-limit", type=int, default=6, help="输出任务数量")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--chunks-csv", type=Path, default=DEFAULT_CHUNKS_CSV)
    parser.add_argument("--faq-csv", type=Path, default=DEFAULT_FAQ_CSV)
    parser.add_argument("--clean-faq-csv", type=Path, default=DEFAULT_CLEAN_FAQ_CSV)
    parser.add_argument("--faq-quality-report-csv", type=Path, default=DEFAULT_FAQ_QUALITY_REPORT)
    parser.add_argument("--task-evidence-csv", type=Path, default=DEFAULT_TASK_EVIDENCE_CSV)
    parser.add_argument("--task-evidence-quality-csv", type=Path, default=DEFAULT_TASK_EVIDENCE_QUALITY_REPORT)
    parser.add_argument("--task-review-report-csv", type=Path, default=DEFAULT_TASK_REVIEW_REPORT)
    parser.add_argument("--task-review-decisions-csv", type=Path, default=DEFAULT_TASK_REVIEW_DECISIONS_CSV)
    parser.add_argument("--task-review-summary-csv", type=Path, default=DEFAULT_TASK_REVIEW_SUMMARY_CSV)
    parser.add_argument("--task-review-pending-export-csv", type=Path, default=DEFAULT_TASK_REVIEW_PENDING_EXPORT_CSV)
    parser.add_argument("--tasks-enriched-csv", type=Path, default=DEFAULT_TASKS_ENRICHED_CSV)
    parser.add_argument("--tasks-reviewed-csv", type=Path, default=DEFAULT_TASKS_REVIEWED_CSV)
    parser.add_argument("--raw-page-index-csv", type=Path, default=DEFAULT_RAW_PAGE_INDEX)
    parser.add_argument("--phase1-manifest-csv", type=Path, default=DEFAULT_PHASE1_MANIFEST)
    parser.add_argument("--schema-dictionary-csv", type=Path, default=DEFAULT_SCHEMA_DICTIONARY)
    parser.add_argument("--vector-index-csv", type=Path, default=DEFAULT_VECTOR_INDEX_CSV)
    parser.add_argument("--vector-backend", choices=["sparse", "chroma"], default="sparse", help="向量索引后端；默认 sparse，可选 chroma")
    parser.add_argument("--retrieval-mode", choices=["keyword", "semantic"], default="keyword", help="检索模式；默认 keyword，可选 semantic")
    parser.add_argument("--chroma-dir", type=Path, default=Path("knowledge_base") / "chroma")
    parser.add_argument("--chroma-collection-name", default="offer_holder_chunks")
    parser.add_argument("--embedding-provider", choices=["hash", "openai"], default="hash", help="向量 embedding 提供方式；默认 hash，可选 openai")
    parser.add_argument("--embedding-dimensions", type=int, default=256)
    parser.add_argument("--openai-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--openai-embedding-model", default="text-embedding-3-small")
    parser.add_argument("--llm-prompt-output", type=Path, default=DEFAULT_LLM_PROMPT_PATH)
    parser.add_argument("--use-openai-response", action="store_true", help="使用 grounded prompt 调用 OpenAI Responses API 生成最终回答")
    parser.add_argument("--openai-model", default=DEFAULT_OPENAI_MODEL)
    parser.add_argument("--openai-max-output-tokens", type=int, default=1200)
    parser.add_argument("--openai-timeout-seconds", type=int, default=60)
    parser.add_argument("--openai-api-key-env-name", default=DEFAULT_OPENAI_API_KEY_ENV, help="读取 OpenAI API key 的环境变量名")
    parser.add_argument("--openai-reasoning-effort", default="medium", help="Responses API reasoning.effort；默认 medium")
    parser.add_argument("--openai-text-verbosity", default="low", help="Responses API text.verbosity；默认 low")
    parser.add_argument("--openai-max-retries", type=int, default=2, help="Responses API 失败时最多重试几次")
    parser.add_argument("--openai-retry-backoff-seconds", type=float, default=2.0, help="Responses API 重试退避秒数基线")
    parser.add_argument("--openai-run-metadata-dir", type=Path, default=Path("data") / "metadata" / "openai_runs", help="Responses API 调试 metadata 输出目录")
    parser.add_argument("--user-state-csv", type=Path, default=DEFAULT_USER_STATE_CSV)
    parser.add_argument("--source-list", type=Path, default=DEFAULT_SOURCE_LIST)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--tasks-csv", type=Path, default=DEFAULT_TASKS_CSV)
    parser.add_argument("--crawl-summary-csv", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--quality-report-csv", type=Path, default=DEFAULT_QUALITY_REPORT)
    parser.add_argument("--build-kb", action="store_true", help="从 data/raw_pages 构建 knowledge_base/chunks.csv")
    parser.add_argument("--export-seed-tasks", action="store_true", help="导出 8 校 x 8 类初始任务模板到 data/cleaned/tasks.csv")
    parser.add_argument("--extract-faq", action="store_true", help="从 raw_pages 抽取 FAQ 候选到 data/cleaned/faq.csv")
    parser.add_argument("--summarize-crawl", action="store_true", help="从 crawl_log.csv 生成最新状态汇总")
    parser.add_argument("--audit-data", action="store_true", help="生成 source/raw/chunks/faq/tasks 覆盖度报告")
    parser.add_argument("--clean-faq", action="store_true", help="清洗 FAQ 候选并生成 faq_cleaned.csv")
    parser.add_argument("--extract-task-evidence", action="store_true", help="从 cleaned FAQ 抽取任务证据到 task_evidence.csv")
    parser.add_argument("--audit-task-evidence-quality", action="store_true", help="审计 task_evidence.csv，生成可人工复核的质量报告")
    parser.add_argument("--prepare-phase1-outputs", action="store_true", help="生成 raw_page_index / phase1_manifest / schema_dictionary")
    parser.add_argument("--enrich-tasks", action="store_true", help="用 task_evidence 生成 tasks_enriched.csv，不覆盖 tasks.csv")
    parser.add_argument("--review-enriched-tasks", action="store_true", help="根据 tasks_enriched.csv 生成人工复核报告，优先标出高歧义任务")
    parser.add_argument("--init-task-review-decisions", action="store_true", help="根据 tasks_enriched_review.csv 初始化人工审核决策表")
    parser.add_argument("--build-reviewed-tasks", action="store_true", help="根据人工审核决策表生成 tasks_reviewed.csv")
    parser.add_argument("--review-pending-summary", action="store_true", help="输出当前待审数量摘要，可配合 --review-school 过滤")
    parser.add_argument("--review-pending-export", action="store_true", help="导出仍待人工审核的任务明细，按学校/优先级排序")
    parser.add_argument("--review-pending-only", action="store_true", help="只导出仍处于 review_pending 的任务或决策行")
    parser.add_argument("--review-school", help="只处理某个学校的 reviewed task 审校流程，例如 HKUST")
    parser.add_argument("--build-vector-index", action="store_true", help="从 chunks.csv 生成无依赖 sparse vector index")
    parser.add_argument("--export-llm-prompt", action="store_true", help="导出基于任务、风险和官方证据的 LLM prompt，不调用外部模型")
    parser.add_argument("--use-enriched-tasks", action="store_true", help="主问答流程使用 tasks_enriched.csv 作为任务源；默认仍使用内置任务模板")
    parser.add_argument("--use-reviewed-tasks", action="store_true", help="主问答流程优先使用 tasks_reviewed.csv 作为任务源")
    parser.add_argument("--min-faq-score", type=int, default=65, help="FAQ 清洗保留的最低质量分")
    parser.add_argument("--all-pages", action="store_true", help="FAQ 抽取时扫描所有 page_type，不只扫描 faq 页面")
    parser.add_argument("--school-filter", action="append", help="FAQ 抽取时按学校筛选；可重复")
    parser.add_argument("--min-answer-chars", type=int, default=30, help="FAQ 候选答案最少字符数")
    parser.add_argument("--max-task-evidence-per-question", type=int, default=8, help="每条 FAQ 最多抽取多少条任务证据")
    parser.add_argument("--max-evidence-items-per-field", type=int, default=3, help="tasks_enriched 每个证据字段最多保留多少条证据")
    parser.add_argument("--vector-max-terms", type=int, default=80, help="vector_index 每个 chunk 最多保留多少个高频词")
    parser.add_argument("--interactive", action="store_true", help="进入简单交互模式")
    parser.add_argument("--debug-json", action="store_true", help="附加输出结构化调试信息")
    return parser


def run_once(args: argparse.Namespace, message: str) -> str:
    school = normalize_school(args.school) or args.school
    intent = route_intent(message, default_school=school)
    profile = build_profile(args, message, intent.school or school)
    if args.user_id and (args.load_user_state or args.save_user_state):
        profile = merge_profiles(load_user_profile(args.user_id, args.user_state_csv), profile)
    task_states = load_task_states_for_args(args, school=profile.school) if args.user_id else {}

    evidence = retrieve_evidence(args, message, profile.school, intent.page_types, intent.stage)

    planner = TaskPlanner(
        tasks_csv=args.tasks_csv,
        task_source_csv=resolve_task_source_csv(args),
    )
    tasks = planner.plan(
        profile,
        intent=intent,
        limit=args.task_limit,
        task_states=task_states,
    )
    risks = RiskChecker().check(profile, tasks=tasks, evidence=evidence, intent=intent)

    prompt = build_grounded_prompt(
        query=message,
        intent=intent,
        profile=profile,
        tasks=tasks,
        risks=risks,
        evidence=evidence,
    )
    response = format_agent_response(
        query=message,
        intent=intent,
        profile=profile,
        tasks=tasks,
        risks=risks,
        evidence=evidence,
    )

    if args.export_llm_prompt:
        write_grounded_prompt(prompt, args.llm_prompt_output)

    if args.use_openai_response:
        run_metadata: dict[str, object] = {}
        try:
            response, _ = generate_grounded_response(
                prompt,
                api_key_env=args.openai_api_key_env_name,
                model=args.openai_model,
                max_output_tokens=args.openai_max_output_tokens,
                timeout_seconds=args.openai_timeout_seconds,
                reasoning_effort=args.openai_reasoning_effort,
                text_verbosity=args.openai_text_verbosity,
                max_retries=args.openai_max_retries,
                retry_backoff_seconds=args.openai_retry_backoff_seconds,
                run_metadata=run_metadata,
            )
            response = ensure_source_citations(
                response,
                tasks=tasks,
                risks=risks,
                evidence=evidence,
            )
        except RuntimeError as error:
            if run_metadata:
                write_openai_run_metadata(
                    {
                        **run_metadata,
                        "fallback_mode": "local_formatted_response",
                        "fallback_reason": str(error),
                    },
                    output_dir=args.openai_run_metadata_dir,
                )
            response = (
                "OpenAI Responses API 暂时不可用，已自动降级为本地格式化回答。\n"
                f"原因：{error}\n\n"
                f"{response}"
            )
        else:
            if run_metadata:
                write_openai_run_metadata(
                    {
                        **run_metadata,
                        "fallback_mode": "",
                        "fallback_reason": "",
                    },
                    output_dir=args.openai_run_metadata_dir,
                )

    if args.save_user_state:
        if not args.user_id:
            raise SystemExit("使用 --save-user-state 时需要同时提供 --user-id。")
        save_user_profile(
            args.user_id,
            profile,
            path=args.user_state_csv,
            notes=args.state_notes,
        )

    if args.debug_json:
        response = response + "\n\nDEBUG:\n" + json.dumps(
            {
                "intent": intent.__dict__,
                "profile": {
                    "school": profile.school,
                    "program_type": profile.program_type,
                    "origin": profile.origin,
                    "completed_flags": sorted(profile.completed_flags),
                    "has_conditional_offer": profile.has_conditional_offer,
                },
                "task_ids": [task.task_id for task in tasks],
                "risk_titles": [risk.title for risk in risks],
                "evidence_ids": [item.chunk.chunk_id for item in evidence],
            },
            ensure_ascii=False,
            indent=2,
        )
    return response


def build_profile(
    args: argparse.Namespace,
    message: str,
    school: str | None,
) -> StudentProfile:
    flags = set(infer_completed_flags(message))
    cli_flag_map = {
        "accepted_offer": args.accepted_offer,
        "paid_deposit": args.paid_deposit,
        "conditions_cleared": args.conditions_cleared,
        "visa_submitted": args.visa_submitted,
        "visa_approved": args.visa_approved,
        "housing_applied": args.housing_applied,
        "tuition_paid": args.tuition_paid,
        "registered": args.registered,
    }
    for flag, enabled in cli_flag_map.items():
        if enabled:
            flags.add(flag)

    has_conditional: bool | None
    if args.has_conditional and args.no_conditional:
        raise SystemExit("--has-conditional 和 --no-conditional 不能同时使用。")
    if args.has_conditional:
        has_conditional = True
    elif args.no_conditional:
        has_conditional = False
    elif "conditional" in message.lower() or "条件" in message:
        has_conditional = True
    else:
        has_conditional = None

    return StudentProfile(
        school=normalize_school(school) or school,
        program_type=args.program_type,
        origin=args.origin,
        completed_flags=flags,
        has_conditional_offer=has_conditional,
    )


def retrieve_evidence(
    args: argparse.Namespace,
    message: str,
    school: str | None,
    page_types: list[str],
    stage: str | None,
) -> list:
    retriever = LocalRagRetriever(raw_dir=args.raw_dir, chunks_csv=args.chunks_csv)
    if args.retrieval_mode == "semantic":
        try:
            semantic_results = search_vector_index(
                message,
                index_csv=args.vector_index_csv,
                backend=args.vector_backend,
                school=school,
                top_k=args.top_k,
                chunks_csv=args.chunks_csv,
                chroma_dir=args.chroma_dir,
                collection_name=args.chroma_collection_name,
                embedding_provider=args.embedding_provider,
                embedding_dimensions=args.embedding_dimensions,
                openai_api_key_env=args.openai_api_key_env,
                openai_embedding_model=args.openai_embedding_model,
            )
            chunk_by_id = {chunk.chunk_id: chunk for chunk in retriever.load_chunks()}
            evidence: list[RetrievalResult] = []
            for item in semantic_results:
                chunk = chunk_by_id.get(item.chunk_id)
                if not chunk:
                    continue
                if page_types and chunk.page_type not in page_types and stage and chunk.stage != stage:
                    continue
                evidence.append(
                    RetrievalResult(
                        chunk=chunk,
                        score=item.score,
                        matched_terms=tuple(),
                    )
                )
            if evidence:
                return evidence
        except Exception:
            pass

    return retriever.search(
        message,
        school=school,
        page_types=page_types,
        stage=stage,
        top_k=args.top_k,
        min_score=1.0,
    )


def run_interactive(args: argparse.Namespace) -> int:
    print("进入 Offer Holder Agent 交互模式。输入 exit / quit 退出。")
    while True:
        try:
            message = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if message.lower() in {"exit", "quit", "q"}:
            return 0
        if not message:
            continue
        print()
        print(run_once(args, message))


def render_user_task_dashboard(args: argparse.Namespace) -> str:
    if not args.user_id:
        raise SystemExit("使用 --list-user-tasks 时需要提供 --user-id。")

    task_states = load_task_states_for_args(args, school=normalize_school(args.school) or args.school)
    profile = load_or_build_profile(args, task_states)
    if not profile.school:
        raise SystemExit("列出个人任务前需要提供 --school，或先通过 --save-user-state 保存带学校的用户状态。")

    planner = TaskPlanner(
        tasks_csv=args.tasks_csv,
        task_source_csv=resolve_task_source_csv(args),
    )
    task_limit = max(args.task_limit, 20)
    tasks = planner.plan(
        profile,
        intent=None,
        limit=task_limit,
        task_states=task_states,
    )
    tasks = filter_tasks_by_status(tasks, args.status_filter)

    lines = [
        f"用户任务清单：{args.user_id}",
        f"学校：{profile.school}；已完成状态：{format_completed_flags(profile.completed_flags)}",
    ]
    if profile.has_conditional_offer is True:
        lines.append("offer 条件：conditional offer")
    elif profile.has_conditional_offer is False:
        lines.append("offer 条件：non-conditional offer")

    tracked_states = collect_visible_task_states(
        task_states,
        include_completed=args.include_completed_tasks,
        status_filter=args.status_filter,
    )
    if tracked_states:
        lines.append(f"已记录单任务状态：{len(tracked_states)} 条")

    if not tasks:
        lines.append("当前没有可展示的进行中任务。")
    else:
        lines.append("")
        lines.append("当前优先任务：")
        for index, task in enumerate(tasks, start=1):
            lines.append(f"{index}. {task.task_name} [{task.stage}]")
            lines.append(f"   task_id: {task.task_id}")
            if task.user_task_status:
                lines.append(f"   状态：{task.user_task_status}")
            if task.user_deadline_at:
                deadline = task.user_deadline_at
                if task.user_deadline_timezone:
                    deadline = f"{deadline} {task.user_deadline_timezone}"
                lines.append(f"   个人截止时间：{deadline}")
                state = task_states.get(task.task_id) or task_states.get(task.task_code)
                trace_parts = []
                if task.user_deadline_source:
                    trace_parts.append(task.user_deadline_source)
                if state and state.deadline_source_ref:
                    trace_parts.append(state.deadline_source_ref)
                if trace_parts:
                    lines.append(f"   截止追溯：{' | '.join(trace_parts)}")
            else:
                lines.append(f"   官方截止依据：{task.deadline}")
            if task.user_reminder_at:
                reminder = task.user_reminder_at
                if task.user_reminder_status:
                    reminder = f"{reminder}（{task.user_reminder_status}）"
                lines.append(f"   提醒：{reminder}")
            if task.human_review_status:
                lines.append(f"   审核状态：{task.human_review_status}")
            official_trace = build_task_trace_summary(task)
            if official_trace:
                lines.append(f"   官方证据摘要：{official_trace}")
            if task.action_url:
                lines.append(f"   入口：{task.action_url}")
            if task.source_url:
                lines.append(f"   官方来源：{task.source_url}")
            lines.append(f"   原因：{task.reason}")

    completed_states = []
    if args.include_completed_tasks:
        completed_states = [
            state
            for state in collect_visible_task_states(
                task_states,
                include_completed=True,
                status_filter=args.status_filter,
            )
            if state.status in {"done", "skipped"}
        ]
    if completed_states:
        lines.append("")
        lines.append("已完成或已跳过：")
        for index, state in enumerate(completed_states, start=1):
            label = state.task_code or state.task_id or "unknown_task"
            lines.append(f"{index}. {label} [{state.status}]")
            if state.deadline_at:
                lines.append(f"   截止时间：{state.deadline_at}")
            if state.notes:
                lines.append(f"   备注：{state.notes}")
    return "\n".join(lines)


def render_user_task_reminders(args: argparse.Namespace) -> str:
    if not args.user_id:
        raise SystemExit("使用 --list-task-reminders 时需要提供 --user-id。")

    school = normalize_school(args.school) or args.school
    task_states = load_task_states_for_args(args, school=school)
    profile = load_or_build_profile(args, task_states)
    tasks_by_key = build_task_lookup(args, profile, task_states)

    reminders = build_task_reminder_rows(
        task_states,
        tasks_by_key=tasks_by_key,
        include_completed=args.include_completed_tasks,
        status_filter=args.status_filter,
    )
    lines = [f"任务提醒清单：{args.user_id}"]
    if profile.school:
        lines.append(f"学校：{profile.school}")
    if not reminders:
        lines.append("当前没有已记录的 deadline 或 reminder。")
        return "\n".join(lines)

    for index, item in enumerate(reminders, start=1):
        lines.append("")
        lines.append(f"{index}. {item['task_name']}")
        lines.append(f"   task_id: {item['task_id']}")
        if item["status"]:
            lines.append(f"   状态：{item['status']}")
        if item["deadline_at"]:
            deadline = item["deadline_at"]
            if item["deadline_timezone"]:
                deadline = f"{deadline} {item['deadline_timezone']}"
            lines.append(f"   截止时间：{deadline}")
        if item["deadline_source"]:
            lines.append(f"   截止来源：{item['deadline_source']}")
        if item["deadline_source_ref"]:
            lines.append(f"   来源备注：{item['deadline_source_ref']}")
        if item["reminder_at"]:
            reminder = item["reminder_at"]
            if item["reminder_status"]:
                reminder = f"{reminder}（{item['reminder_status']}）"
            lines.append(f"   提醒时间：{reminder}")
        if item["official_trace"]:
            lines.append(f"   官方证据摘要：{item['official_trace']}")
        if item["action_url"]:
            lines.append(f"   入口：{item['action_url']}")
        if item["source_url"]:
            lines.append(f"   官方来源：{item['source_url']}")
    return "\n".join(lines)


def render_user_task_agenda(args: argparse.Namespace) -> str:
    if not args.user_id:
        raise SystemExit("使用 --list-task-agenda 时需要提供 --user-id。")

    school = normalize_school(args.school) or args.school
    task_states = load_task_states_for_args(args, school=school)
    profile = load_or_build_profile(args, task_states)
    tasks_by_key = build_task_lookup(args, profile, task_states)
    agenda_timezone = resolve_timezone(args.agenda_timezone)
    reference_date = resolve_agenda_date(args.agenda_date, agenda_timezone)
    agenda_days = max(args.agenda_days, 0)

    items = build_task_agenda_rows(
        task_states,
        tasks_by_key=tasks_by_key,
        include_completed=args.include_completed_tasks,
        status_filter=args.status_filter,
        reference_date=reference_date,
        agenda_days=agenda_days,
        agenda_timezone=agenda_timezone,
    )

    lines = [
        f"任务 agenda：{args.user_id}",
        f"基准日期：{reference_date.isoformat()}（{args.agenda_timezone}）",
        "说明：优先看提醒时间；如果没有可用提醒，就按个人截止时间排序。",
    ]
    if profile.school:
        lines.append(f"学校：{profile.school}")
    if not items:
        lines.append("当前没有落在 agenda 范围内的任务。")
        return "\n".join(lines)

    overdue = [item for item in items if item["bucket"] == "overdue"]
    today_items = [item for item in items if item["bucket"] == "today"]
    upcoming = [item for item in items if item["bucket"] == "upcoming"]
    later_count = sum(1 for item in items if item["bucket"] == "later")

    if overdue:
        lines.extend(render_agenda_section("已逾期：", overdue))
    if today_items:
        lines.extend(render_agenda_section(f"今天（{reference_date.isoformat()}）：", today_items))
    if upcoming:
        lines.extend(render_agenda_section(f"未来 {agenda_days} 天：", upcoming))
    if later_count:
        lines.append(f"更后面还有 {later_count} 条任务未展开；可用 --list-task-reminders 查看完整清单。")
    return "\n".join(lines)


def load_or_build_profile(
    args: argparse.Namespace,
    task_states: dict[str, TaskState],
) -> StudentProfile:
    school_hint = normalize_school(args.school) or args.school or infer_school_from_task_states(task_states)
    profile = build_profile(args, "", school_hint)
    if args.user_id:
        profile = merge_profiles(load_user_profile(args.user_id, args.user_state_csv), profile)
    return profile


def build_task_lookup(
    args: argparse.Namespace,
    profile: StudentProfile,
    task_states: dict[str, TaskState],
) -> dict[str, object]:
    tasks = TaskPlanner(
        tasks_csv=args.tasks_csv,
        task_source_csv=resolve_task_source_csv(args),
    ).plan(
        profile,
        intent=None,
        limit=64,
        task_states=task_states,
    )
    lookup: dict[str, object] = {}
    for task in tasks:
        lookup[task.task_id] = task
        if task.task_code:
            lookup[task.task_code] = task
    return lookup


def load_task_states_for_args(
    args: argparse.Namespace,
    *,
    school: str | None,
) -> dict[str, TaskState]:
    if not args.user_id:
        return {}
    if args.load_task_state or args.list_user_tasks or args.list_task_reminders or args.list_task_agenda:
        return load_user_task_states(
            args.user_id,
            args.task_state_csv,
            school=school,
        )
    return {}


def resolve_task_source_csv(args: argparse.Namespace) -> Path | None:
    if args.use_reviewed_tasks:
        return args.tasks_reviewed_csv
    if args.use_enriched_tasks:
        return args.tasks_enriched_csv
    return None


def filter_tasks_by_status(
    tasks: list[object],
    status_filter: list[str] | None,
) -> list[object]:
    if not status_filter:
        return tasks
    allowed = set(status_filter)
    return [task for task in tasks if getattr(task, "user_task_status", "") in allowed]


def collect_visible_task_states(
    task_states: dict[str, TaskState],
    *,
    include_completed: bool,
    status_filter: list[str] | None,
) -> list[TaskState]:
    seen: set[str] = set()
    rows: list[TaskState] = []
    allowed = set(status_filter or [])
    for state in task_states.values():
        key = state.task_id or state.task_code
        if not key or key in seen:
            continue
        seen.add(key)
        if not include_completed and state.status in {"done", "skipped"}:
            continue
        if allowed and state.status not in allowed:
            continue
        rows.append(state)
    rows.sort(key=lambda item: (sortable_datetime_text(item.deadline_at or item.reminder_at), item.task_id, item.task_code))
    return rows


def build_task_reminder_rows(
    task_states: dict[str, TaskState],
    *,
    tasks_by_key: dict[str, object],
    include_completed: bool,
    status_filter: list[str] | None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for state in collect_visible_task_states(
        task_states,
        include_completed=include_completed,
        status_filter=status_filter,
    ):
        if not state.deadline_at and not state.reminder_at:
            continue
        task = tasks_by_key.get(state.task_id) or tasks_by_key.get(state.task_code)
        rows.append(
            {
                "task_id": state.task_id or state.task_code,
                "task_name": getattr(task, "task_name", "") or state.task_code or state.task_id,
                "status": state.status,
                "deadline_at": state.deadline_at,
                "deadline_timezone": state.deadline_timezone,
                "deadline_source": state.deadline_source,
                "deadline_source_ref": state.deadline_source_ref,
                "reminder_at": state.reminder_at,
                "reminder_status": state.reminder_status,
                "action_url": getattr(task, "action_url", ""),
                "source_url": getattr(task, "source_url", ""),
                "official_trace": build_task_trace_summary(task),
            }
        )
    rows.sort(key=lambda row: (sortable_datetime_text(row["reminder_at"] or row["deadline_at"]), row["task_id"]))
    return rows


def build_task_agenda_rows(
    task_states: dict[str, TaskState],
    *,
    tasks_by_key: dict[str, object],
    include_completed: bool,
    status_filter: list[str] | None,
    reference_date: date,
    agenda_days: int,
    agenda_timezone: timezone,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for state in collect_visible_task_states(
        task_states,
        include_completed=include_completed,
        status_filter=status_filter,
    ):
        deadline_dt = parse_schedule_point(
            state.deadline_at,
            state.deadline_timezone,
            agenda_timezone=agenda_timezone,
            is_deadline=True,
        )
        reminder_dt = None
        if state.reminder_status not in {"dismissed", "disabled"}:
            reminder_dt = parse_schedule_point(
                state.reminder_at,
                state.reminder_timezone,
                agenda_timezone=agenda_timezone,
                is_deadline=False,
            )
        anchor_kind, anchor_dt = choose_agenda_anchor(reminder_dt, deadline_dt)
        if not anchor_dt:
            continue

        task = tasks_by_key.get(state.task_id) or tasks_by_key.get(state.task_code)
        day_delta = (anchor_dt.date() - reference_date).days
        if day_delta < 0:
            bucket = "overdue"
        elif day_delta == 0:
            bucket = "today"
        elif day_delta <= agenda_days:
            bucket = "upcoming"
        else:
            bucket = "later"

        rows.append(
            {
                "task_id": state.task_id or state.task_code,
                "task_name": getattr(task, "task_name", "") or state.task_code or state.task_id,
                "status": state.status,
                "anchor_kind": anchor_kind,
                "anchor_at": anchor_dt,
                "deadline_at": state.deadline_at,
                "deadline_timezone": state.deadline_timezone,
                "reminder_at": state.reminder_at,
                "reminder_timezone": state.reminder_timezone,
                "reminder_status": state.reminder_status,
                "action_url": getattr(task, "action_url", ""),
                "source_url": getattr(task, "source_url", ""),
                "deadline_source_ref": state.deadline_source_ref,
                "official_trace": build_task_trace_summary(task),
                "bucket": bucket,
            }
        )
    rows.sort(key=lambda item: (item["anchor_at"], item["task_id"]))
    return rows


def render_agenda_section(title: str, items: list[dict[str, object]]) -> list[str]:
    lines = ["", title]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {item['task_name']}")
        lines.append(f"   task_id: {item['task_id']}")
        if item["status"]:
            lines.append(f"   状态：{item['status']}")
        lines.append(f"   当前锚点：{item['anchor_kind']} {format_schedule_label(item['anchor_at'], item['anchor_kind'])}")
        if item["deadline_at"]:
            deadline = str(item["deadline_at"])
            if item["deadline_timezone"]:
                deadline = f"{deadline} {item['deadline_timezone']}"
            lines.append(f"   截止时间：{deadline}")
        if item["deadline_source_ref"]:
            lines.append(f"   来源备注：{item['deadline_source_ref']}")
        if item["reminder_at"]:
            reminder = str(item["reminder_at"])
            if item["reminder_timezone"]:
                reminder = f"{reminder} {item['reminder_timezone']}"
            if item["reminder_status"]:
                reminder = f"{reminder}（{item['reminder_status']}）"
            lines.append(f"   提醒时间：{reminder}")
        if item["official_trace"]:
            lines.append(f"   官方证据摘要：{item['official_trace']}")
        if item["action_url"]:
            lines.append(f"   入口：{item['action_url']}")
        if item["source_url"]:
            lines.append(f"   官方来源：{item['source_url']}")
    return lines


def build_task_trace_summary(task: object | None) -> str:
    if task is None:
        return ""
    parts: list[str] = []
    deadline = str(getattr(task, "official_deadline_evidence", "") or "").strip()
    documents = str(getattr(task, "official_document_evidence", "") or "").strip()
    action = str(getattr(task, "official_action_evidence", "") or "").strip()
    fee = str(getattr(task, "official_fee_evidence", "") or "").strip()
    if deadline:
        parts.append(f"deadline: {truncate_trace_text(deadline)}")
    if documents:
        parts.append(f"documents: {truncate_trace_text(documents)}")
    if action:
        parts.append(f"action: {truncate_trace_text(action)}")
    if fee:
        parts.append(f"fee: {truncate_trace_text(fee)}")
    return " ; ".join(parts[:3])


def truncate_trace_text(value: str, *, limit: int = 90) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def infer_school_from_task_states(task_states: dict[str, TaskState]) -> str | None:
    for state in task_states.values():
        if state.school:
            return state.school
    return None


def format_completed_flags(flags: set[str]) -> str:
    if not flags:
        return "无"
    return ", ".join(sorted(flags))


def sortable_datetime_text(value: str) -> str:
    return value.strip() if value else "9999-99-99T99:99:99"


def resolve_timezone(name: str) -> timezone:
    normalized = (name or "").strip()
    if not normalized:
        return timezone.utc
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        fixed_offsets = {
            "Asia/Hong_Kong": 8,
            "Asia/Shanghai": 8,
            "UTC": 0,
        }
        hours = fixed_offsets.get(normalized, 0)
        return timezone(timedelta(hours=hours), name=normalized or "UTC")


def resolve_agenda_date(value: str | None, agenda_timezone: timezone) -> date:
    if value:
        return date.fromisoformat(value)
    return datetime.now(agenda_timezone).date()


def parse_schedule_point(
    value: str,
    timezone_name: str,
    *,
    agenda_timezone: timezone,
    is_deadline: bool,
) -> datetime | None:
    if not value:
        return None

    text = value.strip().replace("Z", "+00:00")
    source_timezone = resolve_timezone(timezone_name) if timezone_name else agenda_timezone
    try:
        if "T" not in text and len(text) <= 10:
            parsed_date = date.fromisoformat(text)
            parsed = datetime.combine(
                parsed_date,
                time(23, 59, 59) if is_deadline else time(9, 0, 0),
                tzinfo=source_timezone,
            )
        else:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=source_timezone)
        return parsed.astimezone(agenda_timezone)
    except ValueError:
        return None


def choose_agenda_anchor(
    reminder_at: datetime | None,
    deadline_at: datetime | None,
) -> tuple[str, datetime | None]:
    if reminder_at and deadline_at:
        if reminder_at <= deadline_at:
            return "提醒", reminder_at
        return "截止", deadline_at
    if reminder_at:
        return "提醒", reminder_at
    if deadline_at:
        return "截止", deadline_at
    return "", None


def format_schedule_label(
    value: datetime,
    anchor_kind: str,
) -> str:
    if anchor_kind == "截止" and value.time() == time(23, 59, 59):
        return value.date().isoformat()
    return value.isoformat(timespec="minutes")


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

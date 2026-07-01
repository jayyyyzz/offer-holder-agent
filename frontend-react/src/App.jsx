import { useEffect, useMemo, useState } from "react";

const DEFAULT_FILTERS = {
  school: "HKUST",
  userId: "",
  taskSource: "reviewed",
  agendaDays: 7,
  agendaTimezone: "Asia/Hong_Kong",
};

const DEFAULT_FORM = {
  status: "",
  deadlineAt: "",
  deadlineTimezone: "Asia/Hong_Kong",
  deadlineSource: "",
  deadlineSourceRef: "",
  reminderAt: "",
  reminderTimezone: "Asia/Hong_Kong",
  reminderStatus: "",
  notes: "",
};

const STAGE_LABELS = {
  offer_acceptance: "Offer 接受",
  visa: "签证",
  housing: "住宿",
  payment: "缴费",
  registration: "注册",
  orientation: "行前准备",
};

const TASK_SOURCE_LABELS = {
  reviewed: "已审核任务",
  enriched: "候选证据任务",
  builtin: "内置模板",
};

export default function App() {
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [draftFilters, setDraftFilters] = useState(DEFAULT_FILTERS);
  const [payload, setPayload] = useState(null);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [formValues, setFormValues] = useState(DEFAULT_FORM);
  const [savedFormValues, setSavedFormValues] = useState(DEFAULT_FORM);

  useEffect(() => {
    void fetchDashboard(filters);
  }, [filters]);

  const tasks = payload?.tasks || [];
  const selectedTask = useMemo(() => {
    if (!tasks.length) {
      return null;
    }
    return tasks.find((task) => task.task_id === selectedTaskId) || tasks[0];
  }, [tasks, selectedTaskId]);

  useEffect(() => {
    if (!selectedTask) {
      setFormValues(DEFAULT_FORM);
      setSavedFormValues(DEFAULT_FORM);
      return;
    }
    setSelectedTaskId(selectedTask.task_id);
    const nextValues = buildFormValues(selectedTask);
    setSavedFormValues(nextValues);
    setFormValues(nextValues);
  }, [selectedTask]);

  const isFormDirty = useMemo(
    () => JSON.stringify(formValues) !== JSON.stringify(savedFormValues),
    [formValues, savedFormValues],
  );

  async function fetchDashboard(nextFilters) {
    setErrorMessage("");
    const params = new URLSearchParams({
      school: nextFilters.school,
      user_id: nextFilters.userId,
      task_source: nextFilters.taskSource,
      agenda_days: String(nextFilters.agendaDays),
      agenda_timezone: nextFilters.agendaTimezone,
    });

    try {
      const response = await fetch(`/api/dashboard?${params.toString()}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      const nextPayload = await response.json();
      setPayload(nextPayload);
      setDraftFilters({
        school: nextPayload.filters.school || nextFilters.school,
        userId: nextPayload.filters.user_id || nextFilters.userId,
        taskSource: nextPayload.filters.task_source || nextFilters.taskSource,
        agendaDays: nextPayload.meta.agenda_days || nextFilters.agendaDays,
        agendaTimezone: nextPayload.meta.agenda_timezone || nextFilters.agendaTimezone,
      });
      if (!nextPayload.tasks?.some((task) => task.task_id === selectedTaskId) && nextPayload.tasks?.length) {
        setSelectedTaskId(nextPayload.tasks[0].task_id);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : String(error));
    }
  }

  function onFilterSubmit(event) {
    event.preventDefault();
    setSaveMessage("");
    setFilters({
      ...draftFilters,
      agendaDays: Number.parseInt(String(draftFilters.agendaDays), 10) || 7,
    });
  }

  function onTaskSourceChange(taskSource) {
    setSaveMessage("");
    setDraftFilters((current) => ({ ...current, taskSource }));
    setFilters((current) => ({ ...current, taskSource }));
  }

  async function onSaveTaskState(event) {
    event.preventDefault();
    if (!selectedTask) {
      return;
    }
    if (!draftFilters.userId.trim()) {
      setSaveMessage("先填写 User ID，才能把个人任务状态写回本地 CSV。");
      return;
    }

    setSaving(true);
    setSaveMessage("");
    try {
      const response = await fetch("/api/task-state", {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          user_id: draftFilters.userId.trim(),
          school: payload?.profile?.school || draftFilters.school,
          task_id: selectedTask.task_id,
          task_code: selectedTask.task_code,
          stage: selectedTask.stage,
          status: formValues.status,
          deadline_at: formValues.deadlineAt,
          deadline_timezone: formValues.deadlineTimezone,
          deadline_source: formValues.deadlineSource,
          deadline_source_ref: formValues.deadlineSourceRef,
          reminder_at: formValues.reminderAt,
          reminder_timezone: formValues.reminderTimezone,
          reminder_status: formValues.reminderStatus,
          notes: formValues.notes,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || `Request failed: ${response.status}`);
      }
      setSaveMessage("个人任务状态已写回 user_task_states.csv。");
      const nextFilters = {
        ...filters,
        userId: draftFilters.userId.trim(),
      };
      setFilters(nextFilters);
      setDraftFilters((current) => ({ ...current, userId: draftFilters.userId.trim() }));
      await fetchDashboard(nextFilters);
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  function onResetTaskState() {
    setFormValues(savedFormValues);
    setSaveMessage("已恢复为当前已保存值。");
  }

  function onClearTaskState() {
    setFormValues({
      ...DEFAULT_FORM,
      deadlineTimezone: savedFormValues.deadlineTimezone || DEFAULT_FORM.deadlineTimezone,
      reminderTimezone: savedFormValues.reminderTimezone || DEFAULT_FORM.reminderTimezone,
    });
    setSaveMessage("已清空当前编辑内容，尚未写回。");
  }

  return (
    <div className="page-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Offer Holder Agent</p>
          <h1>入学准备任务工作台</h1>
          <p className="subtitle">把下一步任务、个人 deadline、提醒和官方证据放到同一张桌面上。</p>
        </div>
        <div className="topbar-status">
          {payload && <SourceStatus payload={payload} userId={draftFilters.userId} />}
        </div>
      </header>

      <section className="control-band">
        <form className="filters" onSubmit={onFilterSubmit}>
          <label className="field">
            <span>学校</span>
            <select
              value={draftFilters.school}
              onChange={(event) => setDraftFilters((current) => ({ ...current, school: event.target.value }))}
            >
              {(payload?.catalog?.schools || []).map((school) => (
                <option key={school.code} value={school.code}>
                  {school.code} · {school.name}
                </option>
              ))}
            </select>
          </label>

          <label className="field grow">
            <span>User ID</span>
            <input
              type="text"
              placeholder="例如 demo_hkust"
              value={draftFilters.userId}
              onChange={(event) => setDraftFilters((current) => ({ ...current, userId: event.target.value }))}
            />
          </label>

          <label className="field narrow">
            <span>Agenda 天数</span>
            <input
              type="number"
              min="0"
              max="30"
              value={draftFilters.agendaDays}
              onChange={(event) => setDraftFilters((current) => ({ ...current, agendaDays: event.target.value }))}
            />
          </label>

          <label className="field">
            <span>时区</span>
            <select
              value={draftFilters.agendaTimezone}
              onChange={(event) => setDraftFilters((current) => ({ ...current, agendaTimezone: event.target.value }))}
            >
              {(payload?.catalog?.timezones || []).map((timezoneName) => (
                <option key={timezoneName} value={timezoneName}>
                  {timezoneName}
                </option>
              ))}
            </select>
          </label>

          <button type="submit" className="primary-button">
            刷新
          </button>
        </form>

        <div className="segmented-control" role="tablist" aria-label="任务源">
          {["reviewed", "enriched", "builtin"].map((source) => (
            <button
              key={source}
              type="button"
              className={`segment${filters.taskSource === source ? " is-active" : ""}`}
              onClick={() => onTaskSourceChange(source)}
            >
              {TASK_SOURCE_LABELS[source]}
            </button>
          ))}
        </div>
      </section>

      {errorMessage ? (
        <section className="notice-band">
          <ul>
            <li>加载 dashboard 失败：{errorMessage}</li>
          </ul>
        </section>
      ) : null}

      {!errorMessage && payload?.empty_hints?.length ? (
        <section className="notice-band">
          <ul>
            {payload.empty_hints.map((hint) => (
              <li key={hint}>{hint}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="metrics-band">
        {(payload ? buildMetrics(payload) : []).map(([label, value]) => (
          <article key={label} className="metric-card">
            <div className="metric-label">{label}</div>
            <div className="metric-value">{value}</div>
          </article>
        ))}
      </section>

      <section className="main-layout">
        <div className="primary-column">
          <section className="section-block">
            <div className="section-heading">
              <div>
                <p className="section-kicker">Today</p>
                <h2>Agenda</h2>
              </div>
              <p className="section-meta">
                {payload ? `${payload.meta.reference_date} · ${payload.meta.agenda_timezone}` : ""}
              </p>
            </div>
            <AgendaSection payload={payload} />
          </section>

          <section className="section-block">
            <div className="section-heading">
              <div>
                <p className="section-kicker">Tasks</p>
                <h2>任务清单</h2>
              </div>
              <p className="section-meta">{tasks.length} 条</p>
            </div>
            <div className="task-list">
              {tasks.length ? (
                tasks.map((task) => (
                  <button
                    key={task.task_id}
                    type="button"
                    className={`task-row${selectedTask?.task_id === task.task_id ? " is-selected" : ""}`}
                    onClick={() => setSelectedTaskId(task.task_id)}
                  >
                    <div className="item-heading">
                      <div>
                        <h3>{task.task_name}</h3>
                        <div className="item-meta">
                          {stageLabel(task.stage)} · {task.risk_level}
                        </div>
                      </div>
                      <Tag value={task.task_status || task.human_review_status || "active"} />
                    </div>
                    <div className="item-trace">{task.reason}</div>
                    <div className="meta-cluster">
                      <Tag tone="accent" value={`证据 ${task.usable_evidence_count}/${task.candidate_evidence_count || task.evidence_count || 0}`} />
                      {task.review_evidence_count ? <Tag tone="warn" value={`待复核 ${task.review_evidence_count}`} /> : null}
                      {task.personal_deadline_at ? <Tag tone="ok" value={`个人截止 ${task.personal_deadline_at}`} /> : null}
                    </div>
                  </button>
                ))
              ) : (
                <EmptyState text="当前没有筛出任务。" />
              )}
            </div>
          </section>
        </div>

        <div className="side-column">
          <section className="section-block">
            <div className="section-heading">
              <div>
                <p className="section-kicker">Reminders</p>
                <h2>提醒与截止</h2>
              </div>
            </div>
            <div className="reminder-list">
              {payload?.reminders?.length ? (
                payload.reminders.map((item) => (
                  <article key={`${item.task_id}-${item.reminder_at || item.deadline_at || "none"}`} className="reminder-item">
                    <div className="item-heading">
                      <h3>{item.task_name}</h3>
                      <Tag value={item.status} />
                    </div>
                    <div className="item-meta">{renderReminderSummary(item)}</div>
                    <div className="item-trace">{buildReminderTrace(item)}</div>
                  </article>
                ))
              ) : (
                <EmptyState text="还没有写入个人 deadline 或 reminder。" />
              )}
            </div>
          </section>

          <section className="section-block detail-block">
            <div className="section-heading">
              <div>
                <p className="section-kicker">Evidence</p>
                <h2>任务详情</h2>
              </div>
            </div>
            {selectedTask ? (
              <TaskDetail
                task={selectedTask}
                userId={draftFilters.userId}
                formValues={formValues}
                savedFormValues={savedFormValues}
                setFormValues={setFormValues}
                saveMessage={saveMessage}
                saving={saving}
                isFormDirty={isFormDirty}
                onSaveTaskState={onSaveTaskState}
                onResetTaskState={onResetTaskState}
                onClearTaskState={onClearTaskState}
                catalog={payload?.catalog || {}}
              />
            ) : (
              <EmptyState text="选择一个任务后，这里会显示个人追溯信息和官方证据。" />
            )}
          </section>
        </div>
      </section>
    </div>
  );
}

function SourceStatus({ payload, userId }) {
  return (
    <>
      <Tag
        asStatus
        tone={payload.filters.task_source_effective === "reviewed" ? "ok" : "warn"}
        value={`任务源：${taskSourceLabel(payload.filters.task_source_effective)}`}
      />
      {payload.filters.task_source_effective !== payload.filters.task_source ? (
        <Tag asStatus tone="warn" value={`请求：${taskSourceLabel(payload.filters.task_source)}`} />
      ) : null}
      <Tag asStatus value={`学校：${payload.profile.school || "未指定"}`} />
      {userId ? <Tag asStatus tone="accent" value={`User ID：${userId}`} /> : null}
    </>
  );
}

function AgendaSection({ payload }) {
  if (!payload?.agenda?.length) {
    return <EmptyState text="当前没有落在 agenda 范围内的任务。" />;
  }

  const groups = [
    ["overdue", "已逾期"],
    ["today", "今天"],
    ["upcoming", `未来 ${payload.meta.agenda_days} 天`],
  ];

  return (
    <div className="agenda-groups">
      {groups.map(([bucket, title]) => {
        const items = payload.agenda.filter((item) => item.bucket === bucket);
        if (!items.length) {
          return null;
        }
        return (
          <div key={bucket} className="agenda-group">
            <p className="agenda-group-title">{title}</p>
            {items.map((item) => (
              <article key={`${item.task_id}-${item.anchor_at}`} className="agenda-item">
                <div className="item-heading">
                  <h3>{item.task_name}</h3>
                  <Tag value={item.status} />
                </div>
                <div className="item-meta">
                  {item.anchor_kind} · {item.anchor_at}
                </div>
                <div className="item-trace">{buildAgendaTrace(item)}</div>
              </article>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function TaskDetail({
  task,
  userId,
  formValues,
  savedFormValues,
  setFormValues,
  saveMessage,
  saving,
  isFormDirty,
  onSaveTaskState,
  onResetTaskState,
  onClearTaskState,
  catalog,
}) {
  const links = collectTaskLinks(task);
  const statusOptions = catalog.task_statuses || [];
  const reminderOptions = catalog.reminder_statuses || [];
  const timezones = catalog.timezones || [];

  return (
    <article className="detail-surface">
      <div className="detail-header">
        <div className="detail-title-row">
          <div>
            <h3>{task.task_name}</h3>
            <p className="detail-copy">{task.description}</p>
          </div>
          <Tag value={task.human_review_status || task.task_status || task.risk_level} />
        </div>
        <div className="detail-chip-row">
          <Tag tone="accent" value={`阶段 ${stageLabel(task.stage)}`} />
          {task.personal_deadline_at ? <Tag tone="ok" value={`个人截止 ${task.personal_deadline_at}`} /> : null}
          {task.review_priority ? <Tag tone="warn" value={`复核优先级 ${task.review_priority}`} /> : null}
        </div>
      </div>

      <div className="definition-grid">
        <Definition label="触发条件" value={task.trigger_condition} />
        <Definition label="个人截止追溯" value={buildPersonalTrace(task)} />
        <Definition label="提醒状态" value={renderReminderDetail(task)} />
        <Definition label="审核状态" value={buildReviewTrace(task)} />
        <Definition label="官方 deadline 证据" value={task.official_deadline_evidence} />
        <Definition label="官方材料证据" value={task.official_document_evidence} />
        <Definition label="官方操作证据" value={task.official_action_evidence} />
        <Definition label="官方费用证据" value={task.official_fee_evidence} />
        <Definition label="证据质量" value={buildEvidenceTrace(task)} />
        <Definition label="排序原因" value={task.reason} />
      </div>

      <section className="editor-block">
        <div className="section-heading compact">
          <div>
            <p className="section-kicker">Writeback</p>
            <h3>个人状态写回</h3>
          </div>
          {userId ? <Tag tone="accent" value={userId} /> : <Tag tone="warn" value="先填写 User ID" />}
        </div>
        <div className="editor-status-row">
          <Tag tone={isFormDirty ? "warn" : "ok"} value={isFormDirty ? "当前有未保存改动" : "当前与已保存值一致"} />
          {task.personal_state_updated_at ? <Tag value={`最近写回 ${task.personal_state_updated_at}`} /> : null}
          {task.personal_status_updated_at ? <Tag value={`状态更新时间 ${task.personal_status_updated_at}`} /> : null}
        </div>
        <div className="saved-summary">
          <Definition label="当前已保存状态" value={renderSavedStateSummary(savedFormValues)} />
        </div>
        <form className="editor-form" onSubmit={onSaveTaskState}>
          <label className="field">
            <span>任务状态</span>
            <select
              value={formValues.status}
              onChange={(event) => setFormValues((current) => ({ ...current, status: event.target.value }))}
            >
              <option value="">未设置</option>
              {statusOptions.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>个人截止</span>
            <input
              type="datetime-local"
              value={formValues.deadlineAt}
              onChange={(event) => setFormValues((current) => ({ ...current, deadlineAt: event.target.value }))}
            />
          </label>

          <label className="field">
            <span>截止时区</span>
            <select
              value={formValues.deadlineTimezone}
              onChange={(event) => setFormValues((current) => ({ ...current, deadlineTimezone: event.target.value }))}
            >
              {timezones.map((timezoneName) => (
                <option key={timezoneName} value={timezoneName}>
                  {timezoneName}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>截止来源</span>
            <input
              type="text"
              placeholder="例如 portal / offer_letter / school_email"
              value={formValues.deadlineSource}
              onChange={(event) => setFormValues((current) => ({ ...current, deadlineSource: event.target.value }))}
            />
          </label>

          <label className="field grow span-2">
            <span>来源备注 / 引用位置</span>
            <input
              type="text"
              placeholder="例如 offer letter p.2 / portal 截图时间"
              value={formValues.deadlineSourceRef}
              onChange={(event) => setFormValues((current) => ({ ...current, deadlineSourceRef: event.target.value }))}
            />
          </label>

          <label className="field">
            <span>提醒时间</span>
            <input
              type="datetime-local"
              value={formValues.reminderAt}
              onChange={(event) => setFormValues((current) => ({ ...current, reminderAt: event.target.value }))}
            />
          </label>

          <label className="field">
            <span>提醒时区</span>
            <select
              value={formValues.reminderTimezone}
              onChange={(event) => setFormValues((current) => ({ ...current, reminderTimezone: event.target.value }))}
            >
              {timezones.map((timezoneName) => (
                <option key={timezoneName} value={timezoneName}>
                  {timezoneName}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>提醒状态</span>
            <select
              value={formValues.reminderStatus}
              onChange={(event) => setFormValues((current) => ({ ...current, reminderStatus: event.target.value }))}
            >
              <option value="">未设置</option>
              {reminderOptions.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>

          <label className="field grow span-2">
            <span>备注</span>
            <textarea
              rows="4"
              value={formValues.notes}
              onChange={(event) => setFormValues((current) => ({ ...current, notes: event.target.value }))}
            />
          </label>

          <div className="editor-actions span-2">
            <button type="submit" className="primary-button" disabled={saving || !isFormDirty}>
              {saving ? "保存中..." : "写回个人状态"}
            </button>
            <button type="button" className="secondary-button" onClick={onResetTaskState} disabled={saving || !isFormDirty}>
              恢复为已保存值
            </button>
            <button type="button" className="ghost-button" onClick={onClearTaskState} disabled={saving}>
              清空当前编辑
            </button>
            {saveMessage ? <p className="form-message">{saveMessage}</p> : null}
          </div>
        </form>
      </section>

      <div>
        <p className="section-kicker">Links</p>
        <div className="link-list">
          {links.length ? (
            links.map((link) => (
              <a key={link} className="task-link" href={link} target="_blank" rel="noreferrer">
                {link}
              </a>
            ))
          ) : (
            <p className="empty-text">当前没有可展示的官方链接。</p>
          )}
        </div>
      </div>
    </article>
  );
}

function Definition({ label, value }) {
  return (
    <dl className="definition">
      <dt>{label}</dt>
      <dd>{value || "暂无"}</dd>
    </dl>
  );
}

function Tag({ value, tone, asStatus = false }) {
  const resolvedTone = tone || inferTone(value);
  const className = asStatus ? "status-pill" : "tag";
  return (
    <span className={className} data-tone={resolvedTone}>
      {value}
    </span>
  );
}

function EmptyState({ text }) {
  return (
    <div className="empty-state">
      <p className="empty-text">{text}</p>
    </div>
  );
}

function buildMetrics(payload) {
  return [
    ["进行中任务", payload.summary.active_task_count],
    ["已记录状态", payload.summary.tracked_state_count],
    ["提醒", payload.summary.reminder_count],
    ["今天", payload.summary.today_count],
    ["逾期", payload.summary.overdue_count],
  ];
}

function buildFormValues(task) {
  return {
    status: task.task_status || "",
    deadlineAt: normalizeDateTimeLocal(task.personal_deadline_at || ""),
    deadlineTimezone: task.personal_deadline_timezone || "Asia/Hong_Kong",
    deadlineSource: task.personal_deadline_source || "",
    deadlineSourceRef: task.personal_deadline_source_ref || "",
    reminderAt: normalizeDateTimeLocal(task.personal_reminder_at || ""),
    reminderTimezone: task.personal_reminder_timezone || "Asia/Hong_Kong",
    reminderStatus: task.personal_reminder_status || "",
    notes: task.personal_notes || "",
  };
}

function normalizeDateTimeLocal(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return `${text}T23:59`;
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text)) {
    return text;
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(text)) {
    return text.slice(0, 16);
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(text)) {
    return text.slice(0, 16);
  }
  return text;
}

function renderSavedStateSummary(values) {
  const parts = [];
  if (values.status) {
    parts.push(`状态 ${values.status}`);
  }
  if (values.deadlineAt) {
    parts.push(`截止 ${values.deadlineAt}`);
  }
  if (values.deadlineSource) {
    parts.push(`来源 ${values.deadlineSource}`);
  }
  if (values.reminderAt) {
    parts.push(`提醒 ${values.reminderAt}`);
  }
  if (values.reminderStatus) {
    parts.push(`提醒状态 ${values.reminderStatus}`);
  }
  if (values.notes) {
    parts.push(`备注 ${values.notes}`);
  }
  return parts.join(" · ") || "当前还没有已保存的个人状态。";
}

function renderReminderSummary(item) {
  const parts = [];
  if (item.deadline_at) {
    parts.push(`截止 ${item.deadline_at}`);
  }
  if (item.reminder_at) {
    parts.push(`提醒 ${item.reminder_at}`);
  }
  return parts.join(" · ") || "暂无时间信息";
}

function buildReminderTrace(item) {
  const parts = [];
  if (item.deadline_source) {
    parts.push(`来源 ${item.deadline_source}`);
  }
  if (item.deadline_source_ref) {
    parts.push(`备注 ${item.deadline_source_ref}`);
  }
  if (item.official_trace) {
    parts.push(item.official_trace);
  }
  return parts.join(" · ") || "暂无追溯信息";
}

function buildAgendaTrace(item) {
  const parts = [];
  if (item.deadline_at) {
    parts.push(`截止 ${item.deadline_at}`);
  }
  if (item.deadline_source_ref) {
    parts.push(`来源 ${item.deadline_source_ref}`);
  }
  if (item.action_url) {
    parts.push("入口已记录");
  }
  return parts.join(" · ") || "暂无额外追溯信息";
}

function buildPersonalTrace(task) {
  const parts = [];
  if (task.personal_deadline_at) {
    parts.push(`${task.personal_deadline_at}${task.personal_deadline_timezone ? ` ${task.personal_deadline_timezone}` : ""}`);
  }
  if (task.personal_deadline_source) {
    parts.push(`来源 ${task.personal_deadline_source}`);
  }
  if (task.personal_deadline_source_ref) {
    parts.push(`备注 ${task.personal_deadline_source_ref}`);
  }
  if (task.personal_notes) {
    parts.push(`备注 ${task.personal_notes}`);
  }
  return parts.join(" · ") || "还没有写入个人 deadline / source_ref。";
}

function renderReminderDetail(task) {
  if (!task.personal_reminder_at) {
    return "还没有写入提醒时间。";
  }
  return `${task.personal_reminder_at}${task.personal_reminder_status ? `（${task.personal_reminder_status}）` : ""}`;
}

function buildReviewTrace(task) {
  const parts = [];
  if (task.human_review_status) {
    parts.push(task.human_review_status);
  }
  if (task.review_decision) {
    parts.push(`decision ${task.review_decision}`);
  }
  if (task.review_notes) {
    parts.push(task.review_notes);
  }
  if (task.review_reason) {
    parts.push(task.review_reason);
  }
  return parts.join(" · ") || "当前任务不在人工复核队列，或尚未生成 reviewed 字段。";
}

function buildEvidenceTrace(task) {
  const parts = [`${task.usable_evidence_count} 可用`];
  if (task.review_evidence_count) {
    parts.push(`${task.review_evidence_count} 待复核`);
  }
  if (task.rejected_evidence_count) {
    parts.push(`${task.rejected_evidence_count} 已排除`);
  }
  if (task.evidence_quality_status) {
    parts.push(task.evidence_quality_status);
  }
  if (task.evidence_quality_notes) {
    parts.push(task.evidence_quality_notes);
  }
  return parts.join(" · ");
}

function collectTaskLinks(task) {
  const urls = new Set();
  if (task.source_url) {
    urls.add(task.source_url);
  }
  String(task.action_url || "")
    .split("|")
    .map((value) => value.trim())
    .filter(Boolean)
    .forEach((value) => urls.add(value));
  String(task.official_action_urls || "")
    .split("|")
    .map((value) => value.trim())
    .filter(Boolean)
    .forEach((value) => urls.add(value));
  return [...urls];
}

function stageLabel(value) {
  return STAGE_LABELS[value] || value || "未分组";
}

function taskSourceLabel(value) {
  return TASK_SOURCE_LABELS[value] || TASK_SOURCE_LABELS.builtin;
}

function inferTone(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized.includes("reject") || normalized.includes("blocked") || normalized.includes("overdue")) {
    return "danger";
  }
  if (normalized.includes("pending") || normalized.includes("review") || normalized.includes("waiting")) {
    return "warn";
  }
  if (normalized.includes("approved") || normalized.includes("done") || normalized.includes("in_progress")) {
    return "ok";
  }
  return "accent";
}

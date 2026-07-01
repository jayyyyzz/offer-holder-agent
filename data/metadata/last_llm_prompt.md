# Role
你是面向内地港校授课型硕士 offer holder 的入学准备助手。

# Non-negotiable rules
- 只能基于下方 task / risk / official evidence 作答。
- 如果没有证据支持具体日期、金额、材料或资格，不要编造；请明确说“当前本地官方归档未找到”。
- 对 deadline、费用、签证、住宿、注册等高风险事项，必须提醒用户以 offer letter、学校 portal、学院邮件和官方 URL 为准。
- 每个涉及 deadline、金额、材料、资格、操作步骤或风险的具体结论，都必须绑定 Evidence ID 和 source_url。
- 如果 task/risk 模板与 official evidence 不一致，以 official evidence 为准；没有 evidence 时只能给通用提醒，不能说成学校官方规则。
- user_task_status、user_deadline_at、user_reminder_at 是用户侧记录；official_deadline_evidence 是官方候选证据，二者不能混同。
- evidence_quality_status 与 usable/review/rejected counts 只表示本地规则审计结果；review/rejected evidence 不能被当作官方结论。
- 输出应是中文，结构包括：当前判断、下一步任务、风险提醒、官方来源。
- 每条关键建议必须附 source_url；没有 source_url 时说明当前本地官方归档未找到可引用来源。

# User query
HKUST student visa next step

# Parsed intent and profile
- school: HKUST
- stage: visa
- intent: task_plan
- origin: Mainland China
- program_type: TPG
- completed_flags: accepted_offer
- has_conditional_offer: None

# Planned tasks
## Task 1: 申请学生签证 / 进入许可
- task_id: hkust-apply_student_visa
- stage: visa
- risk_level: high
- trigger_condition: 决定入读且尚未递交学生签证 / 进入许可申请。
- deadline: 以学校签证页面、邮件及香港入境事务处处理周期为准；不要等到临近开学才递交。
- required_documents: 签证 / 进入许可申请表；旅行证件；录取证明；财力证明；照片；学校要求的其他文件。
- action_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/applying-student-visa
- source_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/applying-student-visa
- reason: 高风险事项，通常会影响入学资格或报到；与你当前提问阶段直接相关；内地学生通常需要办理进入许可 / 学生签证；已匹配 30 条官方证据候选，需以原文复核为准；质量审计：30 条可用，4 条待复核，2 条已排除
- task_code: apply_student_visa
- enrichment_status: evidence_found
- evidence_count: 30
- candidate_evidence_count: 36
- usable_evidence_count: 30
- review_evidence_count: 4
- rejected_evidence_count: 2
- evidence_quality_status: audited
- evidence_quality_notes: 30 keep; 4 review/missing; 2 reject
- official_deadline_evidence: Send us the required paper documents as soon as possible. | Approved visa/ entry permit must be activated on or before the specified date on the e-Visa. | Application period: Fall admission: March or soonest possible Spring admission: mid-October or soonest possible For exchange program, PG visiting student program and visiting internship: apply right after you have accepted the admission offer For DBA, EMBA, MBA, HKUST-NYU MSc in Global Finance: respective program offices will advise you of the details sep...
- official_document_evidence: Send us the required paper documents as soon as possible. | Please refer to the Checklist of Documents Required for Visa/ Entry Permit Application for details. | Please refer to the Checklist of Documents Required for Visa/ Entry Permit Application.
- official_action_evidence: Send us the required paper documents as soon as possible. | Please refer to the Checklist of Documents Required for Visa/ Entry Permit Application for details. | You can check your application status in the Visa System.
- official_action_urls: 
- official_fee_evidence: 
- user_task_status: 
- user_deadline_at: 
- user_deadline_timezone: 
- user_deadline_source: 
- user_reminder_at: 
- user_reminder_status: 
- user_task_notes: 

## Task 2: 缴纳留位费 / admission deposit
- task_id: hkust-pay_deposit
- stage: offer_acceptance
- risk_level: high
- trigger_condition: offer 条款或申请系统要求缴纳 deposit，且尚未完成付款。
- deadline: 通常与接受 offer 的截止日绑定；以 offer letter / portal 的金额与截止时间为准。
- required_documents: 银行卡或汇款信息；付款凭证；application number / student ID。
- action_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/accepting-offer
- source_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/accepting-offer
- reason: 高风险事项，通常会影响入学资格或报到；已接受 offer 后，留位费通常是紧接着要确认的事项；已匹配 5 条官方证据候选，需以原文复核为准；质量审计：5 条可用，0 条待复核，2 条已排除
- task_code: pay_deposit
- enrichment_status: evidence_found
- evidence_count: 5
- candidate_evidence_count: 7
- usable_evidence_count: 5
- review_evidence_count: 0
- rejected_evidence_count: 2
- evidence_quality_status: audited
- evidence_quality_notes: 5 keep; 2 reject
- official_deadline_evidence: Please upload the payment proof by the deadline.
- official_document_evidence: 
- official_action_evidence: Pay the deposit to confirm your acceptance. | If you are a current/ previous student at the University, make sure you have settled all outstanding payment from your studies in order to proceed to new program registration. | Deposit payment instructions will be available after you click “Accept Offer and Pay” in the Online Admission System.
- official_action_urls: 
- official_fee_evidence: 
- user_task_status: 
- user_deadline_at: 
- user_deadline_timezone: 
- user_deadline_source: 
- user_reminder_at: 
- user_reminder_status: 
- user_task_notes: 

# Risks
- [high] 留位费状态未确认
  - detail: 不少 TPG offer 会把 deposit 与 acceptance 绑定；未按时付款可能被视为未接受录取。
  - mitigation: 核对 offer letter 金额、付款方式、到账要求和截止时间；付款后保留凭证。
  - source_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/accepting-offer
- [high] 学生签证 / 进入许可尚未递交
  - detail: 内地学生通常需要 entry permit / student visa 才能以学生身份来港；处理周期不可完全由学生控制。
  - mitigation: 尽早按学校签证页面准备申请表、旅行证件、录取证明和财力材料，递交后持续跟进。
  - source_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/applying-student-visa
- [medium] 线上注册 / 学籍激活未完成
  - detail: 注册常与学生账号、课程、缴费、证件核验或到校流程相连。
  - mitigation: 关注学校 registration guide 和学生系统开放时间，准备证件照片与身份证明文件。
  - source_url: 

# Official evidence
## Evidence 1
- school: HKUST
- page_type: visa
- stage: visa
- title: Applying for Student Visa | HKUST Fok Ying Tung Graduate School
- score: 12.40
- source_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/applying-student-visa
- evidence_id: Evidence 1
- chunk_id: hkust__visa__b221798f94__chunk_000
- matched_terms: hkust, student, visa
```text
Accepting an Offer Submitting Official Documents Applying for Student Visa Handy Resources for Preparing Your Studies Moving to Hong Kong (for Non-Local Students) Sections Text Area Who is a Non-Local Student? A student holding one of the following documents is considered as a non-local student: Student visa/ entry permit; or Visa under the Immigration Arrangements for Non-local Graduates (IANG) ; or Dependent visa/ entry permit , who were 18 years old or above when they were issued with such visa/ entry permit by the Director of Immigration. For more details on definition of non-local students, please visit here . A non-local student who holds student visa/entry permit is not allowed to pursue part-time research postgraduate studies (MPhil/PhD) in Hong Kong. Image Text Area Who Needs Student Visa/ Entry Permit?
```

## Evidence 2
- school: HKUST
- page_type: visa
- stage: visa
- title: Applying for Student Visa | HKUST Fok Ying Tung Graduate School
- score: 12.40
- source_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/applying-student-visa
- evidence_id: Evidence 2
- chunk_id: hkust__visa__b221798f94__chunk_001
- matched_terms: hkust, student, visa
```text
part-time research postgraduate studies (MPhil/PhD) in Hong Kong. Image Text Area Who Needs Student Visa/ Entry Permit? Most non-local students are required to obtain a student visa (or entry permit for students from the Mainland of China, Macao and Taiwan) for studying in Hong Kong. If you are from the Mainland of China, you must apply for an entry permit via HKUST. If you are from Taiwan, Macao or an overseas country, it is the simplest and most straightforward for you to apply for a student visa/ entry permit via HKUST. For students currently studying in Hong Kong (including HKUST), you will have to submit an application for the new program of study at HKUST. However, you don’t need the student visa/ entry permit if you have one of the following for the period of study:
```

## Evidence 3
- school: HKUST
- page_type: visa
- stage: visa
- title: Applying for Student Visa | HKUST Fok Ying Tung Graduate School
- score: 12.40
- source_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/applying-student-visa
- evidence_id: Evidence 3
- chunk_id: hkust__visa__b221798f94__chunk_002
- matched_terms: hkust, student, visa
```text
HKUST. However, you don’t need the student visa/ entry permit if you have one of the following for the period of study: (i) Right of Abode, (ii) Right to Land or (iii) “Unconditional Stay” status in Hong Kong. Check for the symbol “A”, “R” or “U” in the HKSAR smart ID . Dependent visa/ entry permit Visa under the Immigration Arrangements for Non-local Graduates (IANG) Work permit (for part-time students only) In case you are unsure whether you need a student visa/ entry permit or not, please check the FAQs or check with HKSAR Immigration Department (IMMD) [phone: (852) 2824 6111; email: enquiry@immd.gov.hk ]. Steps for Student Visa/ Entry Permit Application via HKUST 1. Accept the Admission Offer Online 2. Log in to the HKUST Visa System via the Online Admission System
```

## Evidence 4
- school: HKUST
- page_type: visa
- stage: visa
- title: Applying for Student Visa | HKUST Fok Ying Tung Graduate School
- score: 12.40
- source_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/applying-student-visa
- evidence_id: Evidence 4
- chunk_id: hkust__visa__b221798f94__chunk_003
- matched_terms: hkust, student, visa
```text
cation via HKUST 1. Accept the Admission Offer Online 2. Log in to the HKUST Visa System via the Online Admission System . Applicants with an accepted offer should find the link to the Visa System in the Application Summary or Offer Details page. Application period: Fall admission: March or soonest possible Spring admission: mid-October or soonest possible Download relevant forms for completion. Settle the fee of HK$1,000 which covers the fee charged by IMMD and cost for forwarding the visa/ entry permit label. 3. Send Visa Application to HKUST Send the completed Visa Application Form together with supporting documents as listed in the Visa System by courier. Use the mailing cover available in the Visa System for the submission. 4. HKUST Submits Your Application to IMMD
```

## Evidence 5
- school: HKUST
- page_type: visa
- stage: visa
- title: Applying for Student Visa | HKUST Fok Ying Tung Graduate School
- score: 12.40
- source_url: https://fytgs.hkust.edu.hk/admissions/Admission-to-Hong-Kong-Campus/after-getting-an-offer/applying-student-visa
- evidence_id: Evidence 5
- chunk_id: hkust__visa__b221798f94__chunk_004
- matched_terms: hkust, student, visa
```text
ourier. Use the mailing cover available in the Visa System for the submission. 4. HKUST Submits Your Application to IMMD Upon receipt of a properly filed application, the University will act as your sponsor, monitor the application progress and update the online visa application status. After IMMD approval, the University will advise you to download the e-Visa for entry to Hong Kong for study. (Note: No need to pay the visa fee for downloading the e-Visa. The University will settle the fee on your behalf.) 5. Before Coming to Hong Kong Ensure that your admission offer is confirmed. (the Online Admission System should show “Offer confirmed – pending program registration” .) If you are from Mainland China, you will have to complete additional steps at your home province after receiving the entry permit which may take another two weeks. 6. Activate the Visa Label upon Entry to Hong Kong
```

# Desired answer
请基于以上信息生成给学生的中文回答。不要提及内部字段名，除非字段名本身对用户有帮助。
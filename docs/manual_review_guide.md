# 人工复核协作指南

本文件用于推进当前数据质量闭环的前两步：

1. 处理 `data_quality_report.csv` 中剩余的 weak 页面。
2. 复核 `faq_quality_report.csv` 中的 `review` / `reject` FAQ 条目。

2026-06-29 点击展开采集 + HKUST manual capture 导入后，你不需要复核全部页面。当前状态：

- 0 个 weak source。
- 0 条 `review` FAQ。
- 4 条 `reject` FAQ，均为已确认噪声/片段/导航项。

对应判定队列见：

```text
data/metadata/manual_review_queue.csv
```

## 你需要怎么配合

### A. HKUST FAQ weak 页面处理结果

HKUST FAQ 自动点击展开仍会被 SafeLine WAF 拦截，但用户已提供官方页面复制文本，并已通过 `crawler.import_manual_page` 导入：

```text
https://fytgs.hkust.edu.hk/admissions/faq
```

对应命令模板：

```powershell
.\.venv\Scripts\python -m crawler.import_manual_page `
  --input "path\to\pasted-text.txt" `
  --school HKUST `
  --page-type faq `
  --source-url "https://fytgs.hkust.edu.hk/admissions/faq" `
  --title "FAQ | HKUST Fok Ying Tung Graduate School"
```

### B. FAQ review / reject 条目当前状态

原先 8 条 FAQ 复核项已经通过 `crawler.expand_faq_pages` 和清洗规则处理：

- CUHK local/non-local applicant processes：已保留，并补上官方链接。
- CUHK visa documents：已保留，并补上 Visa Application 官方链接。
- PolyU entrance requirements：已保留，并补上 admission requirements 官方链接。
- PolyU financial assistance：已保留，并补上 financial assistance 官方链接。
- CUHK visa fragment：保留 reject，句子碎片。
- CUHK PhD fragment：保留 reject，句子碎片。
- HKBU Why HKBU：保留 reject，导航入口，不是 offer-holder FAQ。
- HKUST template noise：已被 manual capture 替代；旧模板噪声不再进入 cleaned FAQ。

如果未来新增 FAQ 页面又出现短答案，可选值建议如下：

- `keep`：保留原清洗结果。
- `discard`：删除，不进入 `faq_cleaned.csv`。
- `fix_question`：问题需要改写；请在 `user_notes` 写新 question。
- `fix_answer`：答案需要补全；请在 `user_notes` 写新 answer 或官方链接。
- `keep_short_with_link`：答案确实很短，但有官方链接支撑，先保留。
- `out_of_scope`：不是 offer holder 入学准备范围。

最省事的方式仍然是直接在聊天里按 review_id 回复，例如：

```text
faq_review_cuhk_local_nonlocal_process = discard
faq_reject_cuhk_visa_fragment = discard
faq_review_cuhk_visa_documents = fix_answer: 这里粘贴官方完整答案或目标链接
```

## 我的处理规则

收到你的判定后，我会：

1. 更新 `manual_review_queue.csv` 的 `user_decision` / `user_notes`。
2. 根据判定修正 `faq_cleaned.csv` 或保持 reject。
3. 重新生成 `faq_quality_report.csv`。
4. 重建 `knowledge_base/chunks.csv`。
5. 重新运行测试和一个检索样例，确认结果可用。

## 当前结论

- `data/cleaned/faq_cleaned.csv`：248 条 keep。
- `data/metadata/faq_quality_report.csv`：248 条 `keep`，4 条 `reject`，0 条 `review`。
- `knowledge_base/chunks.csv`：847 条 chunks。
- `data/metadata/data_quality_report.csv`：56 条 `ok`，0 条 `weak`。

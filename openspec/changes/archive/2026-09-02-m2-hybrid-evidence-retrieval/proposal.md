## Why

剧情问题常使用与官方原文不同的措辞或角色别名。系统需要在生成答案前稳定召回正确官方证据，并能解释排序依据和识别无答案问题。

## What Changes

- 建立实体、别名和实体—片段链接。
- 增加完全本地的字符 TF-IDF 语义索引。
- 将全文、语义、实体、栏目和来源质量组合为混合排序。
- 支持来源类型、版本和语境过滤。
- 提取明确对话说话人并缩小证据块。
- 增加可重复的 Top 1、Top 5 和无答案评测。

## Capabilities

### New Capabilities

- `hybrid-evidence-retrieval`: 可解释、可过滤、可评测的本地官方证据检索。

### Modified Capabilities

无。

## Impact

扩展 SQLite 模型和索引命令；新增实体及评测数据、检索 CLI、回归测试和 M2 报告。

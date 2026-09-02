## Why

剧情问答必须建立在可重复获取、可验证官方身份并能追溯原页面的本地证据库之上。现有 M0 只证明接口可行，需要形成可增量运行的数据管线。

## What Changes

- 增加 Wiki 清单、关键词搜索及官方账号来源发现。
- 保存原始 JSON，并用稳定内容哈希识别真实内容变化。
- 解析 Wiki RPG、Wiki 普通页签和米游社官方文章。
- 将来源、文档、证据片段保存到 SQLite。
- 过滤攻略、推荐、画廊等非剧情证据栏目。
- 建立可自动同步的 SQLite FTS5 索引和 CLI。

## Capabilities

### New Capabilities

- `official-source-ingestion`: 官方来源发现、验证、增量抓取、解析、存储和追溯。

### Modified Capabilities

无。

## Impact

新增 `app/collectors`、`app/parsers`、`app/models` 和 CLI；本地生成 `data/raw` 与 `data/database`，并增加固定样本回归测试。

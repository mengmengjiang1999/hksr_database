# M9 实体感知、有据问答

M9 将“检索到一段相似文本”升级为“先识别问题，再形成有证据约束的回答”。M7 的采集仍可独立运行；每次语料增长后可重跑同一版本的 60 条问题集，区分语料缺口、解析缺陷、实体歧义、排序遗漏、生成失败与正确拒答。

## 当前能力

- 剧情人物与可玩形态分开存储。首个样例把 `姬子`、基础形态 `姬子`、`姬子·启行` 建模为一人两形态。
- `姬子•启行` 是标点变体；`姬子SP` / `姬子sp` 仅标为玩家用语，不作为官方称呼引用。
- 中文问题先归入身份、可玩形态、关系、获取、时间、描述、比较或未知意图。
- 关系回答必须同时命中两个端点，或存在一条带当前官方证据的已审核关系。
- 身份、形态、关系、获取和时间问题优先使用确定性模板；其他问题继续使用原来的抽取式回答。
- 多问一项时只返回有证据的部分；角色形态不明确时要求用户澄清。
- 可选生成器默认没有配置。即使启用，模型也只能读取当次证据包，并且每条声明必须提交逐字证据片段；验证失败、超时或服务错误会回退到确定性答案。

## 评测与维护命令

```bash
.venv/bin/python -m app.cli --database data/database/hksr.sqlite3 m9-build-identities
.venv/bin/python -m app.cli --database data/database/hksr.sqlite3 m9-audit-identities
.venv/bin/python -m app.cli --database data/database/hksr.sqlite3 intent-search '姬子和姬子·启行是什么关系？'
.venv/bin/python -m app.cli --database data/database/hksr.sqlite3 m9-baseline \
  --output data/m9/current-ecs-baseline.json
```

`data/m9/question-taxonomy.json`、`data/m9/real-questions.json` 和 `data/m9/identities.json` 都带独立版本。新增版本资料时，先继续增量抓取和解析，再重建索引、审计身份与关系，最后重跑基线；不需要重新训练模型。

## ECS 灰度与回滚

ECS 用户服务通过 `HKSR_M9_ENTITY_QA_ENABLED` 控制新回答链路。部署文件是 `deploy/hksr-m9.conf`。设置为 `1` 使用 M9；设置为 `0` 后重启 `hksr` 即回到旧的抽取式回答。生成能力与这个开关分离，当前 ECS 未配置任何模型凭据，页面勾选实验性整理时仍会安全回退。

被替换的 ECS 文件保存在 `.deploy-backups/m9-20260904/`。后台 Wiki 采集服务不依赖网页服务重启，并在本次灰度后继续运行。

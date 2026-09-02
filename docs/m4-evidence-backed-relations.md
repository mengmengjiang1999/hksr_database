# M4 带证据知识关联实施报告

> 状态：一跳关系闭环完成
>
> 日期：2026-09-02

## 1. 阶段结论

M4 已实现可审核、可追溯、可失效的一跳关系：

```text
受控关系目录 ─→ 实体与证据选择器校验 ─→ approved 关系

实体共同出现 ─→ co_occurs_with ─→ pending 候选 ─→ 人工审核

当前证据集合 ─→ 稳定 ID 审计 ─→ stale 关系从默认结果隐藏
```

当前没有引入图数据库。SQLite 足以支持本地 MVP 的实体关系卡片和审核流程。

## 2. 关系模型

每条关系保存：

- 主体、谓词、客体；
- `explicit`、`inferred` 或 `candidate` 证据等级；
- `approved`、`pending` 或 `rejected` 审核状态；
- 置信度与推理说明；
- `curated` 或 `cooccurrence` 来源；
- 一条或多条稳定证据 ID；
- 证据是否失效。

### 显式关系

至少需要一条证据，并且同一证据必须链接到关系两端实体。只有主观上“看起来相关”但正文没有同时定位主客体的目录项会被拒绝。

### 推断关系

至少需要两条不同证据和非空推理说明。关系卡片保留 `inferred` 标记，不会呈现为官方原句。

### 共现候选

共现只生成：

```text
predicate = co_occurs_with
evidence_level = candidate
review_status = pending
```

默认 `relations` 查询不会返回这些记录。候选不能直接批准；审核者必须指定语义谓词和 `explicit` 或 `inferred` 等级，并再次通过证据规则。

## 3. 当前数据

| 类型 | 数量 |
| --- | ---: |
| 审核通过关系 | 8 |
| 显式关系 | 7 |
| 推断关系 | 1 |
| 待审核共现候选 | 308 |
| 失效关系 | 0 |

受控目录位于 `data/m4/relations.json`。示例包括姬子与星穹列车、任务与二相乐园、奥赫玛与万帷网等关系。

## 4. CLI

重建关系和候选：

```bash
python3 -m app.cli build-relations
```

查询玩家可见关系：

```bash
python3 -m app.cli relations 姬子
```

管理员查看候选：

```bash
python3 -m app.cli relations 姬子 --include-candidates
```

审核候选：

```bash
python3 -m app.cli review-relation 123 approved \
  --predicate affiliated_with \
  --evidence-level explicit
```

审计失效证据：

```bash
python3 -m app.cli audit-relations
```

## 5. 验证

完整测试目前为 39 项，全部通过。M4 覆盖：

- 显式关系两端实体校验；
- 推断关系多证据要求；
- 共现候选默认隐藏；
- 关系卡片方向和官方引用；
- 证据删除后的失效识别；
- 实体索引重建后审核关系保留；
- 未经语义复核的候选禁止批准。

## 6. 限制

- 当前只有 8 条人工审核关系，不能代表完整知识图谱；
- 308 条候选包含大量同段共现噪声，需要排序和人工审核；
- 谓词仍使用内部英文标识，面向玩家的中文正反向文案留到 M5；
- 关系目录使用原文片段选择器，切分或正文变化后需要重新导入或审核；
- 当前只支持一跳关系，不进行多跳事实推断。

## Why

M2 能召回相关官方文本，但相关性不能保证答案中的每个事实受到支持。系统需要建立程序化可信边界，阻止模型记忆、无引用事实和越界推论进入最终回答。

## What Changes

- 为证据片段生成重解析后仍可追溯的稳定 ID。
- 实现结构化主张、证据绑定和验证结果模型。
- 支持 `explicit`、`inferred`、`uncertain`、`conflicted` 四类结论。
- 对显式主张执行原文支持检查，对推理和冲突执行证据数量及来源规则。
- 默认提供确定性抽取式回答和低置信度拒答。
- 返回引用上下文、栏目、语境、版本和原始链接。
- 增加可重复的主张覆盖率、错误引用和拒答测试。

## Capabilities

### New Capabilities

- `evidence-grounded-answering`: 只允许通过证据验证的结构化主张进入回答。

### Modified Capabilities

无。

## Impact

新增 `app/qa`、`ask` CLI、稳定证据定位和 M3 测试数据；扩展数据库读取接口，但不引入在线模型依赖或 Web API。

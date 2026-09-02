# 崩坏：星穹铁道剧情与设定知识库

一个本地优先、以官方文本为证据边界的剧情与设定问答原型。回答中的每项主张都必须绑定可展开的官方来源；证据不足时系统拒绝补充模型记忆中的事实。

## 当前能力

- 采集并解析官方 Wiki、官方文章、PV 与动画资料；
- 使用全文、字符向量和实体信号进行混合检索；
- 输出逐条主张、稳定证据 ID、原文、上下文和官方链接；
- 展示经过审核并绑定证据的一跳知识关联；
- 提供本地 FastAPI 接口和无需构建的 Web 页面。

## 本地启动

需要 Python 3.9 或更高版本。在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/python -m app.cli initialize
.venv/bin/python -m app.cli serve
```

然后访问 <http://127.0.0.1:8000/>。服务默认只监听回环地址；当前版本没有身份验证，请勿用 `--host 0.0.0.0` 暴露到局域网或公网。

初始化使用已经采集到本地的数据，不会联网。联网同步必须显式调用管理接口：

```bash
curl -X POST http://127.0.0.1:8000/api/admin/sync \
  -H 'content-type: application/json' \
  -d '{"fetch": true}'
```

## 常用命令

```bash
# CLI 问答
.venv/bin/python -m app.cli ask "小三月的纯真有没有失去？"

# 混合检索
.venv/bin/python -m app.cli search "阿格莱雅"

# 查看已审核关系
.venv/bin/python -m app.cli relations "阿格莱雅"

# 运行完整测试
.venv/bin/python -m unittest discover -s tests -v
```

详细设计和阶段结果见 [开发计划](docs/knowledge-qa-plan.md) 与 [M5 实施报告](docs/m5-local-product.md)。

## Why

M1–M4 只能通过 CLI 使用。需要一个可在本机启动、可浏览引用和关系、可查看同步状态的最小产品界面，验证完整用户体验和 API 契约。

## What Changes

- 增加 FastAPI 本地应用和明确的请求/响应模型。
- 提供问答、检索、来源、实体、关系和管理状态接口。
- 提供显式触发的本地同步接口。
- 增加无需构建工具的单页 Web UI。
- 默认服务只监听 `127.0.0.1`。
- 增加 API、静态页面、错误处理和回归测试。
- 增加安装、初始化、启动和操作文档。

## Capabilities

### New Capabilities

- `local-knowledge-app`: 面向本地用户的知识问答 API、管理接口和引用可视化页面。

### Modified Capabilities

无。

## Impact

新增 `app/api`、`web` 和 `serve` 命令；项目依赖增加 FastAPI、Uvicorn 和 HTTPX。本阶段不部署公网服务、不增加账号体系。

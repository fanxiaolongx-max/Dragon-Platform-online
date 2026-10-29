# Dragon-Platform-online · AiOps-Report

[![Python Version](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Uvicorn](https://img.shields.io/badge/Uvicorn-0.29%2B-2c5bb4.svg)](https://www.uvicorn.org/)
[![Platform](https://img.shields.io/badge/Hosted%20On-Dragon%20Platform-7c3aed.svg)](https://github.com/fanxiaolongx-max/Dragon-Platform.git)

**AiOps-Report** 是运营数字人写报告服务（版本 `1.2.5`），专为质量运营与服务合控场景设计。服务串联了指标目录、多源业务数据直查、要素分析与月度/专项报告自动化生成。

本仓库是作为 [Dragon Platform](https://github.com/fanxiaolongx-max/Dragon-Platform.git) 托管 Python 应用的**独立开发与协同仓库**，既支持独立作为 FastAPI 微服务本地运行，也可无缝部署到 Dragon Platform 中台，由平台自动代理并提供在线 IDE、版本回退与双轨数据库挂载。

---

## 🌟 核心特性

- 📊 **运营报告自动生成**：支持月报、周报、质量运营大屏所需的数据要素提取、维度透视与自动化排版渲染。
- 🔎 **441 张 NetCare 业务表直查与映射**：内置《运营指标-索引目录》与业务库落地表完整映射，支持上游源表自动转换为落地表，提供字段白名单校验、多条件组合查询与快速预览。
- ⚡ **高性能异步架构**：基于 FastAPI + Starlette + Uvicorn 异步驱动，支持单进程高并发与标准 OpenAPI 文档（`/docs` 与 `/redoc`）。
- 💻 **Dragon Platform 在线 IDE 深度适配**：
  - 代码在平台内实时热编辑，自带现代深色代码高亮、多 Tab 编辑与优雅拟态弹窗。
  - 绑定独立 Git 仓库（`Dragon-Platform-online.git`），支持在线 Commit、Push、Pull 与历史提交一键版本回滚。
- 🗄️ **双轨数据库隔离体系**：
  - **业务库（只读）**：由平台环境变量 `BUSINESS_DATASOURCE_NAME` 注入，具备安全只读沙箱，防止越权破坏。
  - **应用库（专属读写）**：由 `APP_DATASOURCE_ID=app` 映射到本地独立 SQLite（`db/app.db`），持久化用户配置、自定义查询快照与报告草稿。

---

## 📁 目录结构

```text
Dragon-Platform-online/
├── app/                        # 核心应用源码
│   ├── main.py                 # FastAPI 入口工厂 (create_app)
│   ├── config.py               # Pydantic 环境变量与配置定义
│   ├── db.py                   # 数据库连接池与会话管理
│   ├── core/                   # 核心基础能力 (日志、异常处理、拦截器)
│   ├── dao/                    # 数据访问层 (Data Access Objects)
│   ├── routers/                # REST API 路由层
│   │   ├── health.py           # 健康检查接口 (/health)
│   │   ├── report.py           # 报告生成与管理 (/api/report)
│   │   ├── data_element.py     # 数据要素提取与分析
│   │   ├── data_source.py      # 多数据源配置与切换
│   │   ├── data_query.py       # 业务库 SQL 动态查询与透视
│   │   └── table_map.py        # 441 张源表与业务表映射字典
│   ├── schemas/                # Pydantic 输入输出模型
│   ├── services/               # 核心业务逻辑服务
│   └── utils/                  # 辅助工具函数
├── static/                     # 前端静态页面与资源
│   ├── index.html              # 报告工作台与数据直查主入口
│   ├── api_test.html           # 开发者 API 交互调试台与压测工具
│   ├── aiji9monthreport.html   # 月度报告可视化模版
│   └── adc-chat.js             # 运营助手智能体协同脚本
├── db/                         # 应用本地数据与 SQLite 存储
├── logs/                       # 运行日志输出目录
├── requirements.txt            # Python 依赖清单
├── run.py                      # 本地独立启动脚本 (uvicorn)
├── _platform_host.py           # Dragon Platform 宿主反向代理前缀适配层
├── AiOps-Report.version        # 版本标识文件 (1.2.5)
└── README.md                   # 项目说明文档
```

---

## 🚀 快速开始

### 方式一：独立本地运行

#### 1. 克隆仓库与配置环境

```bash
git clone https://github.com/fanxiaolongx-max/Dragon-Platform-online.git
cd Dragon-Platform-online

# 推荐使用 Python 3.10+ 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

#### 2. 配置环境变量

可创建 `.env` 文件覆盖默认配置（可选）：

```env
APP_NAME=AiOps-Report
APP_VERSION=1.2.5
PORT=5600
WORKERS=1
RELOAD=true
LOG_LEVEL=INFO
```

#### 3. 启动服务

```bash
python run.py
```

服务启动后，默认监听在 `http://127.0.0.1:5600`：
- **报告主页**：[http://127.0.0.1:5600/](http://127.0.0.1:5600/)
- **API 调试台**：[http://127.0.0.1:5600/static/api_test.html](http://127.0.0.1:5600/static/api_test.html)
- **Swagger 接口文档**：[http://127.0.0.1:5600/docs](http://127.0.0.1:5600/docs)
- **健康探测**：[http://127.0.0.1:5600/health](http://127.0.0.1:5600/health)

---

### 方式二：在 Dragon Platform 中托管运行

本服务已无缝适配 **Dragon Platform** 托管体系：

1. **自动前缀穿透**：平台通过 `_platform_host.py` 处理 `X-Forwarded-Prefix` 标头，无论挂载在 `/apps/aiops-report` 还是自定义二级目录，所有静态资源和 API 请求均可自动路由。
2. **在线代码调试**：
   - 在平台右上角的「运行中」状态胶囊点击 **💻 在线修改代码 (IDE)**。
   - 打开全屏暗色 IDE，左侧树浏览代码，右侧多标签高亮编辑，支持保存后直接热测试。
   - 支持通过 Git 面板直接 Push 到本仓库，或随时回退到历史任一安全版本。
3. **数据库信息查看**：
   - 在状态胶囊中点击 **🗄️ 查看分配的数据库**，可直接查看平台为当前应用分配的只读业务库名称与独立读写库路径。

---

## 📡 核心 API 概览

| 接口分类 | 请求方式 | 路由路径 | 作用说明 |
| :--- | :--- | :--- | :--- |
| **基础存活** | `GET` | `/health` | 服务存活探测，返回 `{"status": "healthy"}` |
| **映射字典** | `GET` | `/api/data/table-map` | 获取 441 张源表、模块与业务库落地表的完整映射目录 |
| **业务库查表** | `GET` | `/api/data/tables` | 列出业务库中所有可用落地表（包含数据量与说明标签） |
| **表结构探查** | `GET` | `/api/data/columns/{table}` | 查询目标表的物理字段、注释与类型信息 |
| **数据直查** | `POST` | `/api/data/fetch` | 支持多条件 `AND` 过滤、字段过滤、分页的安全直查 |
| **维度透视** | `POST` | `/api/data/pivot` | 对指定指标进行行列交叉分组与聚合透视分析 |
| **报告生成** | `POST` | `/api/report/generate` | 传入时间周期与指标维度，自动化组装并生成分析报告 |
| **要素管理** | `GET` / `POST` | `/api/data-element/*` | 运营报告核心要素的增删改查与沉淀 |

---

## 🤝 协作与贡献

1. 推荐在独立功能分支（Feature Branch）上修改，完成测试后提交 Pull Request。
2. 保持代码格式整洁，涉及 API 路由变更请同步补充 Pydantic 模型注释。
3. 在 Dragon Platform 内置 IDE 调试时，随时可通过「版本历史」抽屉比对 Diff 或回退至上一个 Commit。

---

## 📄 License

Internal Tooling Project · [Dragon Platform](https://github.com/fanxiaolongx-max/Dragon-Platform.git)

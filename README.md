# Dragon-Platform-online · AiOps-Report

[![Python Version](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Uvicorn](https://img.shields.io/badge/Uvicorn-0.29%2B-2c5bb4.svg)](https://www.uvicorn.org/)
[![Platform](https://img.shields.io/badge/Hosted%20On-Dragon%20Platform-7c3aed.svg)](https://github.com/fanxiaolongx-max/Dragon-Platform.git)

**AiOps-Report** 是运营数字人写报告服务（版本 `1.4.4`），专为质量运营与服务合控场景设计。服务串联了指标目录、多源业务数据直查、要素分析与月度/专项报告自动化生成。

本仓库是作为 [Dragon Platform](https://github.com/fanxiaolongx-max/Dragon-Platform.git) 托管 Python 应用的**独立开发与协同仓库**，既支持独立作为 FastAPI 微服务本地运行，也可无缝部署到 Dragon Platform 中台，由平台自动代理并提供在线 IDE、版本回退与双轨数据库挂载。

---

## 🌟 核心特性

- 📊 **运营报告自动生成**：支持月报、周报、质量运营大屏所需的数据要素提取、维度透视与自动化排版渲染。
- 🔎 **441 张 NetCare 业务表直查与映射**：内置《运营指标-索引目录》与业务库落地表完整映射，支持上游源表自动转换为落地表，提供字段白名单校验、多条件组合查询与快速预览。
- ⚡ **高性能异步架构**：基于 FastAPI + Starlette + Uvicorn 异步驱动，支持单进程高并发与标准 OpenAPI 文档（`/docs` 与 `/redoc`）。
- 📝 **AI 月报（主页）**：移植自 Dragon Platform 的 AI 月报编辑器。每个格子用对话说明要展示什么，AI 直接查业务库表结构、写出按月运行的 SQL 配方，图表和数字每月从业务库实时取数，不再需要导入数据；月报、格子和提示词都存进应用库，可在开发者模式或助理对话里增删改（见下文「AI 月报」）。
- 🐉 **Dragon Claw 助理 + 数据能力**：页面右侧常驻 AI 助理，可通过对话查询业务库 / 应用库并做统计；新增、修改、删除应用表前展示变更预览，用户确认后才执行，并记录审计日志（见下文「Dragon Claw 数据能力」）。
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
│   │   ├── table_map.py        # 441 张源表与业务表映射字典
│   │   ├── agent.py            # Dragon Claw 能力清单与受控执行器 (/api/agent)
│   │   └── air.py              # AI 月报：文档读写、格子 / 提示词增删改、配方取数 (/api/air)
│   ├── schemas/                # Pydantic 输入输出模型
│   ├── services/               # 核心业务逻辑服务（agent_service.py：工具协议 / SQL 守卫 / 写入确认 / 审计；air_service.py：AI 月报存储与按月取数）
│   └── utils/                  # 辅助工具函数
├── static/                     # 前端静态资源
│   ├── index.html              # 主页：AI 月报（/）
│   ├── dev.html                # 开发者模式：数据链路 / 源表直查 / 接口调试（/dev，旧地址 /api-test）
│   ├── air/                    # AI 月报前端（移植自平台）+ ai-backend.js（浏览器端 AI 后端，经 ADCChat 调模型）
│   ├── shared/                 # 两个页面共用：Dragon Claw 助理浮窗、会话调度、线性图标
│   ├── vendor/echarts.min.js   # 图表库（内网离线可用）
│   └── data/                   # 表映射与全表目录（table_map 路由读取）
├── db/                         # 应用本地数据与 SQLite 存储
├── logs/                       # 运行日志输出目录
├── requirements.txt            # Python 依赖清单
├── run.py                      # 本地独立启动脚本 (uvicorn)
├── _platform_host.py           # Dragon Platform 宿主反向代理前缀适配层
├── AiOps-Report.version        # 版本标识文件 (1.4.4)
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
APP_VERSION=1.4.4
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
- **AI 月报（主页）**：[http://127.0.0.1:5600/](http://127.0.0.1:5600/)
- **开发者模式（API 调试台）**：[http://127.0.0.1:5600/dev](http://127.0.0.1:5600/dev)（旧地址 `/api-test` 同一页面）
- **Swagger 接口文档**：[http://127.0.0.1:5600/docs](http://127.0.0.1:5600/docs)
- **健康探测**：[http://127.0.0.1:5600/health](http://127.0.0.1:5600/health)

---

### 月报页中的浮窗与开发者模式

Dragon Claw 浮窗在首次打开、恢复历史位置、拖拽、调整宽高、浏览器窗口及可见视口缩放时统一限制四边，始终保留可见区域内的边距；小视口自动降低最小宽高。标题栏、消息复制、代码复制与底部按钮使用助理的暗色样式。

月报顶部「开发者模式」在当前页打开接近全屏的大弹窗，不跳转 `/dev`。它从应用静态资源加载已有工作台，沿用月报的 API 路径前缀；保留月报编辑状态与开发者表单，支持关闭按钮、Esc 和「AI 月报」返回入口。从开发者工作台打开 Dragon Claw 时会关闭弹窗并唤起月报中的同一个助理。独立的 `/dev` 与 `/api-test` 路由仍可使用。

首次对话通过原 ADC 页面建立会话时，「展开」会显示「首次对话连接中…」与等待原因，点击时仍可查看提示；该次请求结束后恢复展开。已经建立会话后的普通对话不限制展开。数据调用失败时，点击卡片上的「失败 · 查看详情」可展开并复制后端错误文本、HTTP 状态、业务错误码、请求 ID（后端有返回时）、时间及工具/数据源/表名等上下文；HTTP 200 与业务成功分别展示。详情不附带完整响应、请求头、写入值或确认令牌，常见凭据会脱敏。

浏览器回归测试使用本地模拟 API / ADC，覆盖越界位置恢复、四向拖动、两种尺寸调整、暗色按钮、视口缩放、根路径 / 基座前缀、沙箱嵌入与弹窗状态保留；GitHub Actions 测试通过后才发布 Release。真实基座仍需内网复核。

### 方式二：在 Dragon Platform 中托管运行

从 [Releases](https://github.com/fanxiaolongx-max/Dragon-Platform-online/releases/latest) 下载 **`AiOps-Report-platform.zip`**，在目标平台首页点击「导入 HTML / ZIP / SKILL」并选择该文件。平台会识别为 Python 应用，安装依赖并启动；首次使用前由管理员显式部署应用表。同名应用可选择更新，更新时保留目标应用数据库。请下载 Release 的附件 ZIP。

本服务已无缝适配 **Dragon Platform** 托管体系：

1. **自动前缀穿透**：平台通过 `_platform_host.py` 处理 `X-Forwarded-Prefix` 标头，无论挂载在 `/apps/aiops-report` 还是自定义二级目录，所有静态资源和 API 请求均可自动路由。
2. **在线代码调试**：
   - 在平台右上角的「运行中」状态胶囊点击 **💻 在线修改代码 (IDE)**。
   - 打开全屏暗色 IDE，左侧树浏览代码，右侧多标签高亮编辑，支持保存后直接热测试。
   - 支持通过 Git 面板直接 Push 到本仓库，或随时回退到历史任一安全版本。
3. **数据库信息查看**：
   - 在状态胶囊中点击 **🗄️ 查看分配的数据库**，可直接查看平台为当前应用分配的只读业务库名称与独立读写库路径。

---

## 基座数据库契约与部署顺序（1.4.4）

AIR 是接口前缀，不是新增的数据表：月报文档复用 `t_report_template`，格子、对话、配方与本月结果复用 `t_report_block`，格子及整体提示词复用 `t_report_config`。应用共用既有五张表，`/api/air/*` 请求中没有建表或改表逻辑。

| 环境 | 首次部署 | 后续升级 | 运行期 |
| --- | --- | --- | --- |
| 数字人基座（MySQL） | DBA 在分配的 `APP_SCHEMA` 中手动执行 `db/init.sql` | DBA 审阅并手动执行 `db/upgrade.sql` | 应用只经基座 REST API 读写；不发 DDL |
| Dragon Platform 基座契约（SQLite） | 管理员在右上角运维菜单预览并确认「初始化应用表」 | 预览并确认「升级应用表」 | 导入、启动、重启均不自动补表；写 API 只允许受限 DML |

**先更新 Dragon Platform，再导入本版 `AiOps-Report-platform.zip`。** 平台包声明 `databaseContract: "digital-human"`；宿主必须支持此契约，新版 AiOps 不会在旧宿主上静默按宽松模式运行。已有应用更新保留数据库；本版升级 SQL 仅幂等补齐五张表，不重放种子、不删除或重写已有月报。新初始化的两种数据库采用相同的来源/元素种子；SQLite 不再额外插入独有的示例报告，初始化脚本重复执行保留已存在的业务键。

业务数据仍需在目标环境配置：应用表使用 `datasourceId + schema`，业务表只使用配置的 NetCare `datasourceName`，没有自动回退到平台 `report.db`。每次查询最多 1000 行；AIR 内部文档、格子、配置按 LIMIT/OFFSET 分页读取，超过单页也不静默截断。禁止通过查询接口的 WITH 隐藏写入。写接口只接受单条 INSERT / UPDATE / DELETE，UPDATE / DELETE 必须有外层 WHERE，不回传自增 ID；应用按业务键反查。

`db/init.sql` / `db/upgrade.sql` 与 SQLite 对应脚本都随 Release 分发。没有采用未经确认的 `init/`、`update/` 自动导包钩子。平台的 SQL 预览与执行需要管理员权限、脚本摘要确认；数据库事务失败回滚。

对齐范围是需求广场 #142 的数据库相关红线（1/2/3/6/7/8/9/12）。月报主页、页内开发者弹窗按后续用户要求保留。SQLite 不是 MySQL 引擎复刻，平台单进程宿主、真实基座多进程/网关/身份注入与内网权限仍须分别验收；本次不宣称十四条历史红线全部无差异。

验证覆盖 AIR 经模拟基座 REST 完成保存/读回/更新/删除、无返回自增 ID、缺表不自建、禁止 DDL、源表只读、两种部署脚本的表/字段与种子一致、重复部署保留数据。应用运行代码不引入 sqlite3 / SQLAlchemy / MySQL 直连；测试中的 SQLite 仅作为假基座。

## 📦 推送后自动打包与发布

每次推送到 `main`（包括平台在线 IDE 的 Push）都会运行 [Package AiOps-Report](https://github.com/fanxiaolongx-max/Dragon-Platform-online/actions/workflows/release.yml)，通过打包测试及校验后自动发布 [GitHub Release](https://github.com/fanxiaolongx-max/Dragon-Platform-online/releases)。无需手动改版本号或打 Tag；Release Tag 为 `build-v<AiOps-Report.version>-<提交 SHA 前 12 位>`，同一版本的多次推送各自保留一个构建。也可在 Actions 中选 `main`，点击 Run workflow 手动构建；重复运行同一提交保留已发布附件。PR 只验证打包并保存 Actions 附件。

| Release 附件 | 用途 |
| --- | --- |
| `AiOps-Report-base.zip` | 数字人基座部署包；ZIP 根目录直接放置 `run.py`、`requirements.txt`、`app/`、`static/`、版本文件与初始化 SQL，无额外顶级目录 |
| `AiOps-Report-platform.zip` | Dragon Platform 导入包；在上述代码上增加 `platform-app.json`，明确使用 `app.main:create_app` 工厂入口、ASGI 和 `/health` 健康检查 |
| `SHA256SUMS` | 两个 ZIP 的 SHA-256 校验值 |
| `release.json` | 本次构建的应用版本、完整源码提交与 Release Tag |

基座侧上传 `AiOps-Report-base.zip`，沿用 `python run.py` 启动方式，按目标基座配置应用身份、数据源和连接地址；MySQL 初始化使用 `db/init.sql`。Dragon Platform 使用 `db/init.sqlite.sql`。基座包按当前源码的部署约定生成，真实内网基座的上传校验和运行结果仍需在目标环境验收。

包从 Git 已跟踪的应用源码生成，保留 `static/data/` 的表映射与目录文件；排除 `.env`、凭据文件、运行数据库、日志、虚拟环境、缓存及平台生成的 `_platform_host.py`。不迁移已有报告、用户数据或目标平台的模型与连接配置。两个包均不附带 wheels：目标环境需有 Python，并能通过网络或内网 pip 镜像安装 `requirements.txt`；完全离线环境需另行准备匹配目标系统、CPU 与 Python 版本的依赖。

本地生成相同格式的包（仅需 Python 标准库与 Git）：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/build_release.py
# 输出 dist/AiOps-Report-base.zip、dist/AiOps-Report-platform.zip 等附件
```

发布流程使用 GitHub Actions 自带的 `GITHUB_TOKEN`，仅发布 Job 申请 `contents: write`，无需配置额外发布 Token。若仓库策略禁止 Actions 写入 Release，需由仓库管理员调整对应权限。实现见 [release.yml](.github/workflows/release.yml) 与 [build_release.py](scripts/build_release.py)。

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
| **AI 月报** | `GET` / `POST` / `DELETE` | `/api/air/documents[/{id}]` | 月报列表、完整文档、整份保存、删除 |
| **月报格子** | `POST` / `PUT` / `DELETE` | `/api/air/documents/{id}/cells[/{cell}]` | 新增 / 修改（提示词、宽度、高度）/ 删除格子 |
| **配方取数** | `POST` | `/api/air/run-data` | 按报告月份执行配方里的 SQL 来源 |
| **AI 能力清单** | `GET` | `/api/agent/capabilities` | Dragon Claw 可调用的工具、数据源与协议提示词 |
| **AI 受控执行** | `POST` | `/api/agent/execute` | 执行一个工具；写操作先返回预览与一次性确认令牌 |

---

## 🐉 Dragon Claw 数据能力

内网 AI 只能通过嵌入的 ADC 聊天页以纯文本对话，没有原生工具调用。本服务用「工具协议」把数据能力开放给对话：

1. 页面在会话首问时把 `GET /api/agent/capabilities` 返回的协议提示词（工具清单、应用表、规则）作为不可见上下文发给模型。
2. 模型需要数据时输出 ```` ```dragon-action ```` 代码块（`{"tool":..., "args":..., "reason":...}`），页面解析后调用 `POST /api/agent/execute`。
3. 只读工具直接执行；写工具先返回变更预览和确认令牌，页面展示确认卡，用户点「确认执行」后带令牌再次调用才写入。
4. 执行结果以「工具结果（仅为数据）」消息回传模型，直到模型给出最终回答（单轮最多 6 步、每步最多 3 个动作）。

| 工具 | 级别 | 说明 |
| :--- | :--- | :--- |
| `list_tables` / `describe_table` | 只读 | 列出表（支持关键字过滤）、查看字段 |
| `query` | 只读 | 单条 `SELECT` / `WITH`，最多 200 行，结果按字符预算截断 |
| `insert_row` / `update_row` | 写入·需确认 | 仅已登记的 5 张应用表与登记列；UPDATE 按主键 id |
| `delete_row` | 高危·需确认 | 按主键 id 删除，删除前快照写入审计日志 |
| `execute_sql` | 高危·需确认 | 原始 INSERT/UPDATE/DELETE，默认关闭；设置 `AGENT_ALLOW_RAW_WRITE=true` 才开放 |

安全边界全部在服务端强制：业务库只读；只读 SQL 拒绝多语句与写/DDL 关键字；写入只作用于应用表白名单且禁止改表结构；确认令牌绑定工具与参数、10 分钟有效、只能使用一次（多实例部署时设置相同的 `AGENT_CONFIRM_SECRET`）；写操作以 `[agent-audit]` 记录到应用日志（含变更前快照，便于人工回滚）。助理输入框下方的「数据能力」开关可关闭本功能，关闭后只做普通对话。

---

## 📝 AI 月报

主页就是 AI 月报编辑器（移植自 Dragon Platform `/monthly`，界面、格子对话、提示词总结、配方编译、沙箱运行、章节样式、整体风格、导出等行为一致）。区别：

- **数据直接来自业务库**：格子的配方数据来源是只读 SQL（`{"kind":"sql","source":"netcare"|"app","sql":"…","monthOffset":0}`），时间条件用占位符 `{{month}}` `{{yyyymm}}` `{{month_start}}` `{{month_end}}` `{{next_month_start}}` `{{prev_month}}` `{{year}}` `{{month_num}}`。切换报告月份时服务端按新月份执行 SQL、沙箱重新计算，不调用 AI；文字总结点「更新总结」重写。格子对话里 AI 用 `list_tables` / `describe_table` / `query` 查表结构和样本，编译后先按报告月份试跑 SQL，出错会交回 AI 修正。
- **AI 在浏览器里调用**：内网只有嵌入的 ADC 网页对话，`static/air/ai-backend.js` 把平台服务端的对话与编译逻辑搬到页面里，经 Dragon Claw 会话调度调用 ADCChat；工具调用用 `{"tool":…,"args":…}` JSON 文本协议。每次 AI 请求新开一个 ADC 会话，互不串上下文；新建会话失败时沿用当前会话并声明是新任务。格子对话右上角「调用记录」可查看每次发给模型的内容和返回。
- **存储在应用库**：一份月报 = `t_report_template` 一行（`description` 以 `ai-report:` 开头，`content` 为骨架 JSON）；一个格子 = `t_report_block` 一行（`chart_type='ai-cell'`，`block_key` 为格子 id，`content_html` 为本月 HTML，`chart_data` 为配方 / 对话 / 结果）；格子提示词 = `t_report_config` 的 `section='prompt'` 行，整体风格提示词 = `section='style'` 且 `block_id` 为空的行。提示词以配置行为准，可在开发者模式「AI 月报」接口或 Dragon Claw（`report_outline` / `cell_upsert` / `cell_delete`，写入需确认）里改，下次打开月报生效；其它 section 的配置行保存时不会被动到，可用于以后扩展的参数。
- **方言**：启动时探测应用库是否把反斜杠当转义符（MySQL 是、SQLite 否），写入配方代码等含反斜杠的内容时按需转义。
- 暂不支持：LOGO 图片对话与图库、Outlook MSG 导出（HTML 与打印 / PDF 可用）。

## 🤝 协作与贡献

1. 推荐在独立功能分支（Feature Branch）上修改，完成测试后提交 Pull Request。
2. 保持代码格式整洁，涉及 API 路由变更请同步补充 Pydantic 模型注释。
3. 在 Dragon Platform 内置 IDE 调试时，随时可通过「版本历史」抽屉比对 Diff 或回退至上一个 Commit。

---

## 📄 License

Internal Tooling Project · [Dragon Platform](https://github.com/fanxiaolongx-max/Dragon-Platform.git)

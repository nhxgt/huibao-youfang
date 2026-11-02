# 汇报有方

本机单用户日报 / 周报助手。FastAPI 提供接口和前端页面，SQLite 保存设置、草稿和汇报，本地目录保存原始成果。原型页面已接入后端，正式运行不再生成演示数据。

## Windows 分发包

构建命令：`.\build.ps1`。输出 `dist/《汇报有方——智能日报周报》平台.zip`，适用于 Windows 10 / 11 x64，无需安装 Python 或 Node.js。
完整解压后双击 `汇报有方.exe`，程序就绪后自动打开默认浏览器；关闭程序窗口停止服务。默认端口 8000 被占用时会自动分配其他本地端口，实际地址显示在程序窗口。
每位使用者首次填写个人信息和自己的模型 API，生成需要网络及模型服务额度。压缩包只收集应用程序、运行依赖、页面、提示词和公开说明，不包含个人数据或凭据。
设置 `WORK_REPORT_OPEN_BROWSER=0` 可关闭自动打开浏览器；开发源码默认不自动打开，设置为 1 可启用。显式设置 `WORK_REPORT_PORT` 时严格使用该端口，避免测试或集成静默换端口。

## 启动

当前工作区已创建虚拟环境、安装依赖，可以直接运行：

    .\.venv\Scripts\python.exe run.py

然后打开：

- 应用：http://127.0.0.1:8000/
- 交互式 API 文档：http://127.0.0.1:8000/docs
- OpenAPI 规范：http://127.0.0.1:8000/openapi.json

也可以在 PowerShell 运行 .\start.ps1，通过 .\start.ps1 -Port 8002 更换端口。
原 HTML 从文件地址打开时会跳转至默认端口 8000；使用其他端口时请直接访问对应 HTTP 地址。

新环境需要 Python 3.12 或以上版本：

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
    .\.venv\Scripts\python.exe run.py

requirements.txt 声明依赖范围，requirements.lock.txt 锁定本次验证过的完整环境。

## 首次使用

1. 右上角头像 → 个人信息：填写姓名、岗位，可选部门。
2. 右上角头像 → 模型 API 设置：填写模型名称、Base URL、API Key。
3. 保存后再次打开模型设置，可以点击“测试已保存配置”。该操作会发起一次真实模型请求。
4. 日报：选择日期，填写工作内容和 / 或上传成果，生成后核对、编辑并保存。
5. 周报：选择周期，直接关联该周已保存的日报与成果，可填写汇总要求。
6. 点击“下载成果压缩包”获取后端生成的 ZIP。

历史汇报支持按日期搜索：选择日期后，显示当天日报及汇报周期包含该日期的周报；清除日期可恢复全部记录。

模型接口使用 OpenAI 兼容的 POST {Base URL}/chat/completions，要求支持 system/user 消息和非流式文本响应，不绑定某个服务商。
例如 Base URL 是 https://api.example.com/v1，程序会请求其 /v1/chat/completions。
需要模型能按提示返回 JSON；图片分析还需要支持 image_url 视觉输入。

没有配置模型、认证失败、超时、输出不是有效 JSON 或证据引用无效时，接口返回明确错误，不使用模拟内容兜底。
模型结果仍需要人工核对；来源引用校验保证引用存在，不等于能自动判定每句话在语义上完全正确。

## 数据和凭据

- Windows 默认数据目录为当前账户的 %LOCALAPPDATA%\汇报有方\，与安装目录分离，更新或替换程序不会覆盖用户配置与工作数据。
- 目录中的 reports.sqlite3 保存个人信息、模型名称 / 地址、文件元数据、分析缓存、日报、周报及草稿。
- files/ 按随机标识保存原始文件，上传文件名不参与磁盘路径构造；tmp/ 保存下载后自动删除的临时 ZIP。
- API Key 使用 Windows 当前用户范围的 DPAPI 加密后保存到数据库的独立凭据记录，重启时自动读取。明文不落盘、不从查询接口返回，也不会回填浏览器输入框。
- 右上角“模型 API 设置”可更换 Key；留空保存保留已配置的 Key；“清除已保存的 Key”会同时清除持久化记录与进程中的 Key，保留模型名称和地址。
- 加密凭据绑定配置的 Base URL。修改地址仍需填写 Key；凭据损坏或无法在当前账户解密时，界面要求重新填写，不回退为明文存储。
- 没有已保存凭据时可使用 WORK_REPORT_API_KEY 环境变量；保存模型配置后会加密持久化。清除 Key 后，重启不会重新启用旧环境变量。程序不读取 .env 文件。
- 可使用 WORK_REPORT_DATA_DIR 指定数据目录，WORK_REPORT_PORT 指定端口。
- .gitignore 已排除旧版 data/、虚拟环境、构建目录和 .env。备份时请停止服务后复制整个用户数据目录；换电脑或 Windows 账户后通常需要重新填写 Key。
- 移除当前日报里的附件只改变附件选择，不直接删除其他历史汇报使用的原文件。

每个 Windows 账户各自使用独立数据目录；单个服务仍是本机单用户模式，没有登录或互联网部署配置，默认只监听 127.0.0.1。
后端写操作要求同源并携带 X-Work-Report: 1；这用于防止其他网页误调用本地服务，不是用户身份认证。

## 从旧版迁移与打包

旧版项目内 data/ 不会自动导入其他用户的安装。本人升级时先停止旧服务，再显式复制旧数据：

    .\.venv\Scripts\python.exe -m backend.migrate_data --source .\data

迁移会保留旧目录，不覆盖目标目录中已有的用户内容。旧版只在内存中的 Key 无法迁移，需要在升级后保存一次。

work-report.spec 使用资源白名单，仅收集程序、前端和提示词；不收集 data/、用户数据目录或 .env。安装包不会携带开发者或其他用户的配置、Key、日报及成果。首次安装的用户自行填写自己的 API 配置。

需要生成 Windows 独立程序时，先安装构建依赖，再运行：

    .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
    .\build.ps1

产物目录为 dist\汇报有方\，并生成 dist\《汇报有方——智能日报周报》平台.zip 分发包。整个目录一同分发，不能只复制 EXE。运行其中的汇报有方.exe 后自动打开浏览器，实际地址显示在程序窗口。打包资源与加密实现均不要求用户数据可写入安装目录。
压缩前会检查分发内容，发现数据库、旧版 data/、用户 files/ 或 .env 时拒绝生成压缩包。

## 文件处理与命名

- 单个成果最大 50 MB；日报单次最多分析 30 个文件，周报累计最多分析 210 个文件。
- 文本：TXT、Markdown、CSV、TSV、JSON、XML、HTML、SVG 等。
- Office：DOCX 正文和表格、XLSX 单元格、PPTX 文字和表格；不执行宏、代码或公式。
- PDF：提取文字；扫描件无可提取文字时明确提示，不伪造识别结果。
- 图片：PNG、JPEG、WebP 等经本地缩放后交给视觉模型分析。
- 不支持解析或损坏的文件仍保留原件，可参与 ZIP，不会仅凭文件名生成工作事实。
- 文件有读取页数、行列和字符上限，达到上限会在预览的“需要核对的信息”中说明。

日报压缩包：20261020_产品经理_林晓_工作汇报.zip

包内文件：01_需求评审纪要_20261020.docx

周报压缩包：10月第4周_产品经理_林晓_工作汇报.zip

周报使用周一至周日，包含每月 1 日的那周为第 1 周。跨月周统一归入下个月，只在下个月的周选择列表中显示。
例如 2027-08-30 至 2027-09-05 归为“9月第1周”，8月列表不显示“第6周”；同一周内任一日期得到的周次名称一致。
周报文件按日报日期、原附件顺序连续编号，保留成果所属日。

## 接口

所有 JSON 写请求添加 Content-Type: application/json 和 X-Work-Report: 1。
文件上传是原始二进制请求体，使用 application/octet-stream，不是 multipart。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | /api/health | 服务状态 |
| GET | /api/bootstrap | 页面初始信息、模型状态、最近汇报 |
| GET / PUT | /api/profile | 个人信息 |
| GET / PUT | /api/model-settings | 模型配置，查询只返回是否持有 Key |
| POST | /api/model-settings/test | 实际连接和结构化输出测试 |
| POST | /api/files?report_date=YYYY-MM-DD&filename=文件名 | 上传一个文件的原始字节 |
| GET | /api/files?report_date=YYYY-MM-DD | 当日已上传文件 |
| GET | /api/files/{file_id}/download | 下载原件 |
| POST | /api/reports/daily/generate | 根据文字和文件事实生成日报 |
| POST | /api/reports/weekly/generate | 根据本周日报及附件生成周报 |
| GET | /api/weeks/{anchor_date}/sources | 周范围、周次、日报与成果 |
| GET | /api/reports | 历史汇报，支持 kind/start/end/on_date/q/limit/offset |
| GET / PUT | /api/reports/{daily或weekly}/{report_date} | 查看或保存汇报 |
| GET / PUT | /api/drafts/{daily或weekly}/{report_date} | 查看或保存草稿 |
| POST | /api/archives | 下载成果 ZIP |

生成与保存是独立操作。生成返回 status / items / warnings；保存接收 points / notes / file_ids 等字段。
expected_revision 防止多页面覆盖保存；周报生成响应的 source_revisions 应原样传入保存请求，以检测日报来源更新。
前端已处理这两类版本冲突，周报草稿按自然周共享。

错误结构为 {"error":{"code":"...","message":"..."}}。
参数错误还包含字段位置与说明，不回显原始输入或 API Key。
API Key 仅接受可打印的 ASCII 密钥字符，不接受中文、内部空白、控制字符或纯密码遮罩；校验失败不会覆盖原有配置。
历史保存值或环境变量中的 Key 格式无效时，配置状态会标记 credential_error，测试和生成返回明确的密钥错误；原有加密记录保留，重新填写真实 Key 后恢复。

## 提示词

模型 system 消息由公共规则与任务提示词组合，实际数据作为独立 user 消息传入：

- backend/prompts/common.txt：事实边界、材料指令隔离、表达与输出规则。
- backend/prompts/file.txt：提取成果事实与来源位置。
- backend/prompts/daily.txt：生成日报。
- backend/prompts/weekly.txt：生成周报。

修改文件分析提示词会使对应分析缓存失效。日期、周次、原件保存、重命名和 ZIP 均由程序处理。
周报会为日报要点和文件事实提供明确的 D1 / F1 等引用编号，并将模型引用映射回真实来源。引用缺失或无效时只自动校正一次，仍无效则返回错误，不给无依据事项自动附加来源。

## 验证

    .\.venv\Scripts\python.exe -m unittest discover -s tests -v
    node --check frontend/app.js

接口测试使用隔离临时数据库、真实文件和 HTTPX MockTransport 模拟模型服务，覆盖持久化、解析、中文 ZIP、跨月周次、错误处理、凭据及来源版本。
浏览器联调同样使用隔离测试服务，不会向运行目录写入演示数据。
浏览器回归需要 Node.js 能找到 Playwright（可通过 NODE_PATH 指定其 node_modules 目录），以及已安装的 Chrome。
在一个终端启动隔离服务：

    .\.venv\Scripts\python.exe -m tests.browser_server

在另一个终端依次运行：

    node tests/frontend-regressions.cjs
    node tests/frontend-workflow.cjs

每轮完整验证前重新启动隔离服务，获得干净的临时数据库。测试脚本默认使用 8001 端口并写入测试记录，不要将 TEST_BASE_URL 指向日常使用的数据服务。

未提供真实服务商凭据，因此真实模型质量、具体服务商兼容性与账单尚未验证；配置后可用“测试已保存配置”验证。

实现参考：[FastAPI 文档](https://fastapi.tiangolo.com/)、[HTTPX 超时配置](https://www.python-httpx.org/advanced/timeouts/)、[HTTPX Client API](https://www.python-httpx.org/api/)。

<p align="center">
  <strong>简体中文</strong> · <a href="README.en.md">English</a> · <a href="README.ja.md">日本語</a> · <a href="README.mars.md">吙煋呅</a>
</p>

<h1 align="center">PDF 自动翻译与归档</h1>

<p align="center">
  免费、非商业化的 PDF 翻译软件，支持图片文字 OCR、原位排版和文档级翻译辅助。
</p>

<p align="center">
  <a href="https://github.com/Larryppg/auto_pdf_translator/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/Larryppg/auto_pdf_translator/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Software free" src="https://img.shields.io/badge/software-100%25%20free-brightgreen">
  <img alt="Non-commercial project" src="https://img.shields.io/badge/project-non--commercial-blue">
  <img alt="Current API" src="https://img.shields.io/badge/current%20API-DeepSeek-6f42c1">
</p>

> [!IMPORTANT]
> **软件本体完全免费，并以非商业化方式开发和维护。** 不收许可证费、订阅费或功能费。
> 安装完成后，只需在本机 `.env` 中加入你自己的 DeepSeek API Key 即可使用。
> DeepSeek 是第三方 API，其账户、额度和可能产生的调用费用不包含在“软件免费”范围内。

> [!NOTE]
> **当前版本暂时以 DeepSeek OpenAI 兼容 API 为默认并完成实际验证。** 代码保留了通用
> OpenAI-compatible 接口配置能力，但其他服务商尚未作为正式支持后端逐一测试。

## 应用截图

<p align="center">
  <a href="docs/images/gui-main.png"><img src="docs/images/gui-main.png" alt="GUI 主界面与 AI 设置" width="49%"></a>
  <a href="docs/images/gui-completed.png"><img src="docs/images/gui-completed.png" alt="GUI 翻译完成状态" width="49%"></a>
</p>
<p align="center"><sub>真实 Windows GUI：文件选择、思考模式与预检测开关，以及完成后的进度和任务结果。点击图片可查看原图。</sub></p>

### 图片文字与原位排版效果

<p align="center">
  <a href="docs/images/demo-source.png"><img src="docs/images/demo-source.png" alt="翻译前的合成演示 PDF" width="49%"></a>
  <a href="docs/images/demo-translated.png"><img src="docs/images/demo-translated.png" alt="翻译后的合成演示 PDF" width="49%"></a>
</p>
<p align="center"><sub>左：英文原文件；右：简体中文译文。示例由程序实际处理，包含原生 PDF 文字和图片内文字，不含私人数据。</sub></p>

## 为什么选择它

- **翻译图片中的文字**：本地 OCR 识别 PDF 插图、扫描区域和截图中的文字，再交给翻译模型。
- **尽量保留原文字位置与格式**：使用原文本框、对齐方式、颜色、背景采样和自适应字号进行原位回填，而不是输出纯文本译稿。
- **翻译前预检测文档语境**：自动识别主题、领域、关键词、专名、缩写和依赖语境的多义词，并把建议译法注入后续批次。
- **思考模式可开关**：可以为每次 GUI 入队任务独立选择是否使用 DeepSeek 思考模式。
- **预检测可开关**：可以为每次任务独立决定是否执行文档预分析；简单文档可直接翻译以节省时间。
- **自动监听与归档**：新 PDF 加入 `source/` 后自动触发，验证输出后再归档工作副本。
- **可追踪、可恢复**：提供批次进度、ETA、重试、完整性检查、manifest、失败记录和内容哈希去重。

这是一个独立实现的 Windows/Python 工作流：可以通过 GUI 选择 PDF，也可以把 PDF 放入
`source/`。程序会等待文件复制完成，翻译 PDF 原生文字和图片内文字，原位排版生成新 PDF，
验证成功后再把工作副本按日期归档。

## 工作流

```text
source/ 新文件
      │
      ▼
文件大小与修改时间稳定检查 ── 避免读取尚未复制完的 PDF
      │
      ▼
原生文字提取 + 图片区域 OCR ── 重叠文字去重
      │
      ▼
文档主题、关键词、专名与歧义词预分析
      │
      ▼
带稳定 ID 的分批翻译 ── 文档上下文、术语表、重试、响应完整性校验
      │
      ▼
按原框遮盖 + 背景色采样 + 译文自适应缩放
      │
      ▼
.partial.pdf 写入及页数/可读性验证
      │
      ▼
translated/ 原子保存 + archive/YYYY/MM/DD/ 原件归档
```

程序不会直接覆盖源文件。翻译输出写完并验证前，原件一直留在 `source/`；处理失败的文件会移动到 `failed/YYYY/MM/DD/`，并生成同名 `.error.json` 记录完整错误。任务状态、哈希和日志保存在 `.state/`。

## 安装

需要 Windows、Python 3.11 或更高版本，以及 DeepSeek API Key。翻译接口采用 OpenAI 兼容格式。

在 PowerShell 中运行：

```powershell
cd E:\Study\Human-Anatomy-Physiology-AI\pdf_translation_workflow
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

安装脚本会创建 `.venv`、安装依赖并从 `.env.example` 生成 `.env`。随后编辑 `.env`：

```dotenv
OPENAI_API_KEY=你的 DeepSeek API Key
```

程序默认使用 DeepSeek；也可以通过环境变量覆盖服务地址和模型：

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
```

OCR 在本机运行；发送给翻译接口的是识别后的文字及稳定 ID，不会发送 PDF 页面图片。

## 密钥与隐私

仓库中的 `.env.example` 只有占位符。请复制为本机 `.env` 后填写自己的 DeepSeek API Key，
不要把真实 Key 写入 README、`config.toml` 或提交到 GitHub。即使是专门为本项目新建的 Key，
也不应进入 Git；如果 Key 曾被提交或公开，应立即在服务商控制台撤销并重新创建。

`.env`、`.venv`、`.state`、`source`、`translated`、`archive` 和 `failed` 已由
`.gitignore` 整体排除，避免上传密钥、私人 PDF、OCR 内容、译文、manifest、错误记录和日志。

## GUI 使用（推荐）

双击项目根目录下的 `启动PDF翻译GUI.cmd`，然后点击“选择并翻译 PDF…”。可以一次选择
一个或多个文件，不需要修改配置或输入命令。GUI 会显示：

- 本次选择的原文件和 `source` 工作副本；
- 当前提取/OCR、文档预分析、AI 翻译、排版、验证及归档进度；
- 翻译批次百分比和 ETA；
- 完成、重复复用或失败状态；
- 实时日志，并可直接打开译文或输出文件夹。

选择文件前可以独立设置两个开关：

- `开启思考模式`：打开后，该批新加入文件的预分析与翻译请求使用 DeepSeek 思考模式；
  可能提高复杂语境判断，但通常更慢。
- `开启文档预分析`：打开后，正式翻译前识别主题、领域、关键词、专名、缩写和多义词；
  关闭后直接分批翻译。

开关状态在点击“选择并翻译 PDF…”时锁定，只影响这一次选择的新文件，不改变已经排队或
正在处理的任务。任务列表会显示每份文件实际使用的组合。GUI 默认为“思考关、预分析开”。

从桌面、下载目录或其他目录选择 PDF 时，GUI 只会把它安全复制到 `source/`，原位置的
文件不会移动或删除。后续被归档的是这份工作副本。如果选择的文件本来就在 `source/`，
则不再重复复制，由监听器按原有规则处理和归档。

GUI 会检查后台监听器：未运行时自动隐藏启动；已经运行时直接复用。关闭 GUI 不会停止
后台监听，因此新加入 `source/` 的文件仍会自动触发。

GUI 会为工作副本写入一个临时的无密钥任务设置文件。监听器读取后为该 PDF 选择对应的
翻译引擎，完成或失败后自动清理；实际生效值同时写入 manifest。手动把文件放入 `source/`
或使用原脚本时没有该任务设置文件，因此继续使用 `config.toml` 的默认值。

## 脚本与命令行备份入口

原有工作流没有被 GUI 替换。双击 `一键启动PDF翻译器.cmd` 仍可使用带控制台日志的监听
方式；`scripts/start_watcher.ps1`、`pdf-translator watch/once/status/doctor` 也继续可用。
即使 GUI 出现问题，仍可完全独立地使用这些入口。

使用脚本监听时，保持弹出的窗口开启，再把 PDF 复制到 `source/`；窗口会直接显示提取、
预分析、翻译批次、ETA、排版、验证、保存和归档进度。重复启动不会创建第二个监听实例。

如果修改了配置或更新了程序，请先在原窗口按 `Ctrl+C` 停止，再重新双击启动入口。

命令行方式仍然保留，适合诊断：

先做环境检查：

```powershell
.\.venv\Scripts\python.exe -m pdf_translation_workflow --config .\config.toml doctor
```

持续监听：

```powershell
.\scripts\start_watcher.ps1
```

然后把 PDF 复制到 `source/`。输出名称包含目标语言和源内容哈希，例如：

```text
translated/paper.simplified-chinese.a1b2c3d4.pdf
translated/paper.simplified-chinese.a1b2c3d4.manifest.json
archive/2026/09/01/paper.pdf
```

只处理一次、不持续监听：

```powershell
.\.venv\Scripts\python.exe -m pdf_translation_workflow --config .\config.toml once
```

查看最近任务：

```powershell
.\.venv\Scripts\python.exe -m pdf_translation_workflow --config .\config.toml status
```

日志文件为 `.state/workflow.log`。

## 登录后自动运行

确认手动监听正常后，安装当前用户的 Windows 计划任务：

```powershell
.\scripts\install_autostart.ps1
```

它会在登录后以隐藏窗口启动监听器，同一目录只允许一个监听实例。卸载自动启动：

```powershell
.\scripts\uninstall_autostart.ps1
```

## 配置

主要设置位于 `config.toml`：

- `[paths]`：监听、输出、归档、失败隔离和状态目录。
- `[translation]`：源/目标语言、接口地址、模型、思考模式、重试、请求批量和固定术语表。
- `[document_analysis]`：翻译前的主题、关键词、专名和歧义术语预分析。
- `[ocr]`：是否识别图片文字、置信度和渲染 DPI。
- `[layout]`：最小/最大字号、遮盖边距、行高、背景采样和可选字体。
- `[watch]`：文件稳定等待、扫描间隔、工作线程数和是否递归监听。
- `[archive]`：日期目录、原文件名和清单开关。

固定术语可直接写进 TOML：

```toml
[translation.glossary]
organoid = "类器官"
extracellular_matrix = "细胞外基质"
```

DeepSeek V4 默认启用思考模式。本项目默认为翻译和文档预分析都发送：

```toml
[translation]
thinking_mode = "disabled"
```

这样通常更快。可选值为 `disabled`、`enabled` 和 `provider_default`。为保持非思考翻译的
术语一致性，程序会先均匀抽取整份文档的代表性文字，识别主题、领域、关键词、专名、
缩写及多义词，再把精简的分析结果注入每个翻译批次。分析结果会写入同名
`.manifest.json`。预分析失败时默认记录错误并继续翻译；若必须分析成功才能翻译，可设置：

```toml
[document_analysis]
enabled = true
required = true
sample_characters = 18000
max_keywords = 24
max_terms = 48
```

如目标语言需要指定字体，推荐配置包含完整字符集的 `.ttf` 或 `.otf`：

```toml
[layout]
font_file = "C:/Windows/Fonts/msyh.ttc"
```

留空时 PyMuPDF 的 HTML 排版器会使用内置回退字体。

## 可靠性设计

- 监听事件只用于发现文件；程序还会每 30 秒扫描一次，避免丢失文件系统事件。
- 同一内容由 SHA-256 识别。重复文件不再次调用翻译接口，而是归档到 `archive/duplicates/` 并复用已有输出。
- 翻译请求按字符数分批，每段有稳定 ID；缺项会单独补译，不能静默漏段。
- AI 阶段显示批次编号、区域数、字符数、完成百分比、单批耗时和预计剩余时间。
- 文档级预分析使用跨页均匀样本，结果既注入批次，也保存在 manifest 中供追溯。
- API 错误使用指数退避重试；最终失败会保留原件和错误追踪信息。
- 输出先写到 `.state/*.partial.pdf`，重开验证页数后才原子替换到 `translated/`。
- SQLite 使用 WAL、忙等待和单实例锁，降低断电、重复启动和并发写入风险。
- 图片 OCR 只接受显示图片范围内的结果，并与 PDF 原生文字按几何重叠率去重。
- 长译文使用原框自适应缩放，保留原来的左/中/右对齐倾向；背景色从文字框边缘采样。

## 已知边界

- 密码保护 PDF 会进入 `failed/`，不会尝试绕过密码。
- 手写字、复杂数学公式、弧形/旋转图片文字以及极低清晰度扫描件，OCR 和回填效果取决于原稿质量。
- 图片中文字会被矩形区域遮盖后写入可搜索译文；复杂纹理背景不会进行生成式重绘，因此可能看到色块。
- 为保证正文不丢失，译文过长时可能缩到配置的最小字号以下，并在日志中给出警告。
- 表单域、特殊图层、数字签名和高级 PDF 交互内容建议先用副本验证；任何修改都会使原数字签名失效。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

测试覆盖配置路径、批量翻译不漏项、响应 JSON 解析、PDF 原子输出、源文件归档和内容哈希去重。

<p align="center">
  <a href="README.md">简体中文</a> · <strong>English</strong> · <a href="README.ja.md">日本語</a>
</p>

<h1 align="center">Automatic PDF Translation & Archiving</h1>

<p align="center">
  A free, non-commercial PDF translator with image OCR, layout-preserving replacement, and document-aware translation assistance.
</p>

<p align="center">
  <a href="https://github.com/Larryppg/pdf-translation-workflow/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/Larryppg/pdf-translation-workflow/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Software free" src="https://img.shields.io/badge/software-100%25%20free-brightgreen">
  <img alt="Non-commercial project" src="https://img.shields.io/badge/project-non--commercial-blue">
  <img alt="Current API" src="https://img.shields.io/badge/current%20API-DeepSeek-6f42c1">
</p>

> [!IMPORTANT]
> **The software itself is completely free and is developed and maintained as a non-commercial project.**
> There are no license, subscription, or feature fees. After installation, you only need to add your own
> DeepSeek API key to the local `.env` file. DeepSeek is a third-party API; account requirements, quotas,
> and possible API usage charges are separate from this free software.

> [!NOTE]
> **The current release is temporarily based on and tested with DeepSeek's OpenAI-compatible API.**
> The configuration can point to another OpenAI-compatible endpoint, but other providers have not yet
> been individually validated as officially supported backends.

## Key advantages

- **Translate text inside images** — local OCR detects text in figures, screenshots, and scanned regions before translation.
- **Preserve the original text position and formatting as closely as possible** — translated text is written back into the original boxes with alignment, color, background sampling, and adaptive font sizing.
- **Pre-detect document context** — the program identifies the subject, domain, keywords, proper names, abbreviations, and context-dependent ambiguous terms before batch translation.
- **Optional thinking mode** — enable or disable DeepSeek thinking independently for each group of files submitted through the GUI.
- **Optional document pre-analysis** — enable it for technical terminology consistency or disable it for simpler and faster jobs.
- **Automatic watching and archiving** — a new PDF in `source/` is detected automatically; the working copy is archived only after output validation.
- **Traceable and recoverable** — batch progress, ETA, retries, completeness checks, manifests, failure records, and hash-based deduplication are included.

## How it works

```text
Select PDFs in the GUI or add them to source/
                 │
                 ▼
Wait until each file is stable and fully copied
                 │
                 ▼
Extract native PDF text + run local OCR on image regions
                 │
                 ▼
Optional subject, keyword, terminology, and ambiguity pre-analysis
                 │
                 ▼
Stable-ID batch translation with glossary and completeness checks
                 │
                 ▼
Replace text in the original boxes with adaptive layout
                 │
                 ▼
Write a partial PDF, reopen it, and validate page readability
                 │
                 ▼
Atomically save to translated/ and archive the working copy
```

The original file selected from Desktop, Downloads, or another external directory is not moved. The GUI
copies it safely into `source/`; only that working copy is archived. The program never overwrites the
selected original PDF.

## Requirements

- Windows
- Python 3.11 or later
- Your own DeepSeek API key

OCR runs locally. The API receives extracted text with stable identifiers, not rendered PDF page images.

## Quick start

```powershell
git clone https://github.com/Larryppg/pdf-translation-workflow.git
cd pdf-translation-workflow
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

The setup script creates `.venv`, installs dependencies, and creates a local `.env` from `.env.example`.
Open `.env` and enter your own key:

```dotenv
OPENAI_API_KEY=replace-with-your-own-deepseek-api-key
```

The environment variable keeps the `OPENAI_` name because DeepSeek exposes an OpenAI-compatible API.
The default configuration is:

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
```

Never commit the real `.env` file or any API key.

## GUI usage

Double-click `启动PDF翻译GUI.cmd`, then select **选择并翻译 PDF…**. Multiple PDFs may be submitted
at once. The GUI shows extraction/OCR, pre-analysis, AI translation, layout, validation, saving, and
archiving progress, including translation percentages and ETA.

Before choosing files, two independent switches are available:

- **开启思考模式 / Enable thinking mode** — applies DeepSeek thinking to the submitted job. It may help with difficult context but is usually slower.
- **开启文档预分析 / Enable document pre-analysis** — identifies the document subject, domain, keywords, names, abbreviations, and ambiguous terms before translation.

The switch values are captured when the files are submitted. Changing the controls later does not affect
files already queued or running. Defaults are **thinking off** and **pre-analysis on**.

Closing the GUI does not stop the background watcher. The original console launcher
`一键启动PDF翻译器.cmd`, PowerShell scripts, and CLI remain independent backup interfaces.

## CLI and watched-folder mode

Environment check:

```powershell
.\.venv\Scripts\python.exe -m pdf_translation_workflow --config .\config.toml doctor
```

Continuous watcher:

```powershell
.\scripts\start_watcher.ps1
```

One-time processing:

```powershell
.\.venv\Scripts\python.exe -m pdf_translation_workflow --config .\config.toml once
```

Recent jobs:

```powershell
.\.venv\Scripts\python.exe -m pdf_translation_workflow --config .\config.toml status
```

## Configuration highlights

`config.toml` controls paths, source and target languages, the model and endpoint, fixed glossary entries,
OCR confidence and DPI, layout fitting, watcher behavior, and archiving.

```toml
[translation]
thinking_mode = "disabled" # disabled, enabled, or provider_default

[document_analysis]
enabled = true
required = false
sample_characters = 18000
max_keywords = 24
max_terms = 48

[translation.glossary]
organoid = "类器官"
extracellular_matrix = "细胞外基质"
```

GUI per-job switches override only thinking mode and pre-analysis for the selected files. Files manually
added to `source/` continue to use the defaults in `config.toml`.

## Privacy and security

`.env`, `.venv`, `.state`, `source`, `translated`, `archive`, and `failed` are excluded from Git. These
locations may contain private PDFs, OCR text, translated content, manifests, local paths, errors, or logs.
If a key is ever committed or published, revoke it immediately and create a replacement; deleting it in a
later commit does not remove it from Git history.

## Known limitations

- Password-protected PDFs are not bypassed.
- OCR quality depends on image resolution and clarity.
- Handwriting, curved or rotated text, dense formulas, and highly textured backgrounds remain difficult.
- Image text is covered with sampled background rectangles before translated searchable text is inserted; complex backgrounds may show visible patches.
- Long translations may require a smaller font and generate a warning.
- Editing a digitally signed PDF invalidates the original signature.

## Tests and license

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The project is distributed under the MIT License. The project itself is maintained as free, non-commercial
software; third-party API terms and charges remain the responsibility of the API account owner.

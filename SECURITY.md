# Security

## API keys

Never commit a real DeepSeek or other provider API key. Store the key only in
the local `.env` file or the operating system environment. The repository
tracks `.env.example` solely as a placeholder template.

If a key is ever committed or published, revoke it in the provider console and
create a replacement. Removing the text in a later commit is not sufficient,
because the original value remains in Git history.

## PDF data

The runtime directories `source/`, `translated/`, `archive/`, `failed/`, and
`.state/` are excluded from Git. They may contain private documents, OCR text,
translation manifests, local paths, errors, or logs.

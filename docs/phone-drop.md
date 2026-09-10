# Phone drop: pod -> Hugging Face -> Telegram

`send-phone` is a durable handoff for files produced on disposable GPU pods.
The pod uploads to a private Hugging Face Storage Bucket at pod/HF speed, then a
small worker on the home Docker host downloads the queued file and hands it to
the existing local Telegram Bot API server.

Hugging Face Storage Buckets are intentionally used instead of a model/dataset
repository: bucket objects are mutable and non-versioned, so successfully
delivered files can be permanently deleted without leaving large Git history.

## Queue protocol

Each job is stored as:

```text
inbox/<job-id>/
  payload.tar
  ready.json
```

The payload is uploaded first and `ready.json` last. The worker only consumes a
job after `ready.json` exists, so a killed/interrupted pod cannot expose a
half-uploaded file as ready.

After Telegram confirms delivery the worker writes `delivered.json` to its persistent
local spool and then to HF before cleanup. That marker is an idempotency fence: if HF cleanup is interrupted, the
worker finishes cleanup on the next poll rather than sending the file twice.
`delivered.json` is deleted last.

## Pod usage

The first invocation creates a small, isolated venv with a current
`huggingface_hub`; this deliberately does not touch the older HFF/ML-compatible
Hub version used elsewhere in pod-runtime.

```bash
send-phone /workspace/qwen3/report.tar
send-phone /workspace/qwen3/report.tar --caption "Blind-set run after pose changes"
```

Defaults:

- bucket name: `pod-phone-drop` (created private under the HF token owner)
- prefix: `inbox`
- maximum queued file: 1.9 GB

Useful overrides:

```bash
export PHONE_DROP_BUCKET=owner/custom-phone-drop
export PHONE_DROP_PREFIX=inbox
export PHONE_DROP_MAX_BYTES=1900000000
```

When `send-phone` reports `queued`, the pod may be terminated immediately.

## Home Docker worker

The worker needs a write-capable HF token for the same bucket, the Telegram bot
token, and the target Telegram chat ID. `deploy/phone-drop/compose.example.yml`
is a standalone example; it can also be copied into the existing compose tree.

The worker uses the existing `telegram-bot` container over `t3_proxy`.

### Required change to the existing Telegram Bot API service

Enable local mode and share the phone-drop spool read-only:

```yaml
services:
  telegram-bot:
    environment:
      TELEGRAM_API_ID: "..."
      TELEGRAM_API_HASH: "..."
      TELEGRAM_LOCAL: "1"
    volumes:
      - $DOCKERDIR/appdata/telegram-bot/data:/var/lib/telegram-bot-api
      - $DOCKERDIR/appdata/phone-drop:/phone-drop:ro
```

The worker downloads into `/spool/<job-id>/...`; both containers see the same
host directory, with the Telegram API container seeing it as `/phone-drop`.
Telegram therefore sends `file:///phone-drop/<job-id>/<filename>` directly and
the worker does not make a second multi-hundred-MB HTTP upload to the Bot API.

If this bot has never been moved from Telegram's hosted Bot API to the local API
server, call the Bot API `logOut` method once before using it locally. If the bot
already works through this local server, do not repeat that migration step.

## Worker environment

Required:

```text
HF_TOKEN
TELEGRAM_BOT_TOKEN      (TG_BOT_TOKEN is also accepted)
TELEGRAM_CHAT_ID        (TG_CHAT_ID is also accepted)
```

Optional:

```text
PHONE_DROP_BUCKET=pod-phone-drop
PHONE_DROP_PREFIX=inbox
PHONE_DROP_POLL_SECONDS=20
PHONE_DROP_SPOOL=/spool
TELEGRAM_API_BASE=http://telegram-bot:8081
TELEGRAM_LOCAL_FILE_ROOT=/phone-drop
PHONE_DROP_TELEGRAM_TIMEOUT=3600
```

On Telegram/HF failure the HF job is retained for retry. A partially downloaded
local spool file is reused if its size matches the manifest.

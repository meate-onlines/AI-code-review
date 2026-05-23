# AI-code-review

[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

English | [中文](./README_CN.md)

An extensible AI code review tool built on **LangChain + GitLab**.
Team standards live as Skills and are injected into the prompt on demand. Supports both CLI
and Webhook triggers, ships with a Skill test framework and LangSmith / local token
observability.

![alt text](image.png)

---

## Features

- **LangChain-powered pipeline**: any OpenAI-compatible endpoint (DashScope / DeepSeek / OpenAI / private gateway), structured output, retries and concurrency out of the box.
- **Skills system**: company standards are written as `standards/<lang>/<rule>.md` files. YAML front-matter describes when to trigger; the body is injected into the prompt when matched.
- **Hard + semantic fallback matching**: deterministic rules cover the obvious cases, embedding-based retrieval (with a local cache) catches the rest.
- **Skill test framework**: each rule ships with `<skill>.tests.yml` covering both violating and compliant samples. `--no-ai` gives a zero-cost CI gate.
- **Observability**: rich terminal tables for token usage and skill-hit distribution; optional LangSmith tracing.
- **Two triggers**: CLI (replaces cron) or FastAPI Webhook (reviews fire as soon as an MR opens, with dedupe and concurrency control).

---

## Project layout

```
.
├── app/
│   ├── settings.py              # pydantic-settings configuration
│   ├── chains/                  # LangChain chain: schemas / prompts / review_chain
│   ├── skills/                  # Skill loader, selector, semantic index
│   ├── adapters/                # GitLab IO / diff parsing / language detection
│   ├── pipeline/                # Orchestration: fetch -> select skills -> review -> publish
│   ├── testing/                 # Skill test runner
│   ├── webhook/                 # FastAPI Webhook service
│   ├── observability.py         # LangSmith + local UsageCollector
│   └── cli.py                   # Typer CLI entrypoint
├── standards/                   # Team standards library (.md + .tests.yml per rule)
│   ├── general/
│   ├── java/
│   └── python/
├── config.example.yml           # Example configuration
├── main.py                      # Backwards-compatible entry (equivalent to `review today`)
└── requirements.txt
```

---

## Installation

```bash
git clone https://github.com/meate-onlines/AI-code-review.git
cd AI-code-review
pip install -r requirements.txt
cp config.example.yml config.yml      # fill in real token / api_key
```

---

## Usage

### 1. One-shot CLI (replaces the old `main.py`)

```bash
# Review all MRs updated today
python -m app.cli review today

# Review a specific MR (local debugging)
python -m app.cli review mr <project_id> <mr_iid> -v

# Offline single-file review (no comments posted, useful for prompt tuning)
python -m app.cli review file path/to/Foo.java
```

### 2. Webhook mode (real-time, recommended for production)

```bash
# Start the service
python -m app.cli serve

# Or run uvicorn directly
uvicorn app.webhook.app:create_app --factory --host 0.0.0.0 --port 8000
```

Then in **GitLab → Project → Settings → Webhooks** add:

| Field | Value |
|---|---|
| URL | `https://<host>/gitlab/webhook` |
| Secret Token | must match `webhook.secret` in `config.yml` |
| Trigger | tick **Merge request events** |

Endpoints:

- `GET /healthz` — liveness probe
- `GET /ready` — readiness probe (verifies GitLab connectivity)
- `GET /usage` — JSON of cumulative tokens / skill hits

### 3. Skills

```bash
# List all loaded standards
python -m app.cli skills list

# Preview which skills a given file would hit
python -m app.cli skills match src/main/java/com/foo/UserMapper.xml

# Run skill tests (includes AI calls)
python -m app.cli skills test
python -m app.cli skills test --skill java-naming-convention -v

# Trigger-only validation (no AI, CI-friendly)
python -m app.cli skills test --no-ai

# Semantic index management
python -m app.cli skills index status
python -m app.cli skills index rebuild
```

---

## Configuration (`config.yml`)

See `config.example.yml` for the full file. Highlights:

```yaml
ai:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "sk-xxxx"
  model: "qwen-coder-plus"

review:
  include_patterns: ["**/*.java", "**/*.py", ...]
  exclude_patterns: ["**/generated/**", ...]
  concurrency: 4
  comment_min_severity: warning

skills:
  enabled: true
  standards_dir: "standards"
  hard_match_floor: 2          # enable semantic fallback when hard matches < 2
  semantic:
    enabled: false             # opt-in; reuses ai.api_key by default
    model: "text-embedding-v3"
    min_score: 0.55

webhook:
  enabled: true
  port: 8000
  secret: "<change-me>"
  max_concurrent_reviews: 2
  dedupe_ttl_seconds: 1800

langsmith:
  enabled: false               # local usage summary still works when disabled
  api_key: "lsv2_pt_xxxx"
  project: "ai-code-review"
  local_summary: true
```

Any field can be overridden via environment variables:
`REVIEW__AI__API_KEY=...`, `REVIEW__WEBHOOK__SECRET=...`.

---

## Adding a new standard

1. Create `standards/<lang>/<name>.md`:

   ```markdown
   ---
   name: java-log-spec
   description: Java logging standard. Use when reviewing Java code that writes logs.
   severity: warning
   triggers:
     languages: [java]
     file_patterns: ["**/*.java"]
     keywords: ["log.", "logger."]
   tags: [java, logging]
   ---

   # Java logging standard
   ## Rules
   ...
   ## Bad examples
   ...
   ## Good examples
   ...
   ```

2. Add a sibling `<name>.tests.yml` with both violating and compliant samples.
3. `python -m app.cli skills test --skill java-log-spec` to verify.
4. If semantic matching is enabled: `python -m app.cli skills index rebuild`.

---

## Contributing

1. Fork the repo
2. Create a feature branch
3. Add your changes (please include skill tests when adding a rule)
4. Open a Pull Request

---

## License

Released under the [MIT License](LICENSE).

---

## Contact

- Email: fmj_lg@163.com
- GitHub: [meate-onlines](https://github.com/meate-onlines)

---

## Acknowledgments

- [LangChain](https://www.langchain.com/)
- [python-gitlab](https://python-gitlab.readthedocs.io/)
- [Alibaba Cloud DashScope (Qwen)](https://help.aliyun.com/zh/dashscope/)
- [FastAPI](https://fastapi.tiangolo.com/)

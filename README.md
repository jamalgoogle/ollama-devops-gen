# 🤖 AI DevOps Toolkit

**A growing collection of AI-assisted automation tools for DevOps and cloud engineers, built local-first on [Ollama](https://ollama.com).**
Use large language models to remove repetitive infrastructure work (containers, pipelines, scripts, analysis)
while keeping your code private and a human in control.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![LLM](https://img.shields.io/badge/LLM-local%20first-orange)
![License](https://img.shields.io/badge/license-MIT-lightgrey)
![Status](https://img.shields.io/badge/status-active-success)

---

## 📌 Overview

DevOps work is full of tasks that are important but repetitive: writing Dockerfiles, wiring CI/CD pipelines,
reviewing configs, reading logs. Modern LLMs can produce a solid first draft of all of these, but a raw chat
answer is not something you should commit or deploy.

**AI DevOps Toolkit** turns that idea into small, practical command-line tools that:

1. **Read your real project** (files, manifests, infrastructure code) instead of guessing.
2. **Ask a local model** to produce the artifact.
3. **Validate the result** with code before anything is written.
4. **Show you what changes** and let you approve, reject or roll back.

The goal is simple: *AI writes the first draft, automation checks it, an engineer decides.*

## ✨ Principles

| Principle | What it means in this project |
|---|---|
| 🔒 **Local-first & private** | Models run through Ollama on your machine or your own server. Nothing goes to a third-party API unless you choose to point a tool at one. |
| 📦 **Minimal dependencies** | Tools are plain Python scripts that rely on the standard library. Optional extras are clearly marked. |
| ✅ **Validate, then write** | Model output is parsed and checked. Invalid output is rejected and the model is asked again. |
| 👀 **Human in the loop** | Diffs, confirmation prompts, `--dry-run` modes and automatic backups. |
| 🧩 **Small, composable tools** | One tool, one job. Each tool works alone, from a terminal, a git hook, a cron job or a CI step. |
| 🔁 **Reproducible & explainable** | Low model temperature, explicit rules in prompts, and clear logs of what happened. |

## 🧰 Tools

| Tool | Area | What it does | Docs |
|---|---|---|---|
| [`tools/generate_dockerfile.py`](tools/generate_dockerfile.py) | Containers | Scans a project (or takes a stack name), writes a production-grade `Dockerfile` + `.dockerignore`, builds the image, and feeds build errors back to the model to self-correct. | [docs/dockerfile-generator.md](docs/dockerfile-generator.md) |
| [`tools/cicdgen.py`](tools/cicdgen.py) | CI/CD | Generates a pipeline for GitHub Actions, GitLab CI or Jenkins and **auto-updates** it when dependencies, Dockerfile or infrastructure files change. | [docs/cicd-generator.md](docs/cicd-generator.md) |

> More tools will be added over time. See the [roadmap](#-roadmap) and [adding a new tool](#-adding-a-new-tool).

## 📁 Repository structure

```text
ai-devops-toolkit/
├── tools/                      # Runnable command-line tools (one file per tool)
│   ├── generate_dockerfile.py
│   └── cicdgen.py
├── docs/                       # One detailed guide per tool
│   ├── dockerfile-generator.md
│   └── cicd-generator.md
├── requirements.txt            # Optional extras (PyYAML)
├── .gitignore
├── LICENSE                     # MIT
└── README.md                   # You are here
```

## ⚙️ Requirements

| Requirement | Needed for |
|---|---|
| Python 3.8+ | All tools |
| [Ollama](https://ollama.com) (local or reachable over the network) | All tools |
| A pulled model, default `qwen2.5-coder:7b` | All tools |
| Docker (running) | Tools that build images |
| Git | Tools that detect the branch or create commits |
| `pip install pyyaml` | Optional, for strict YAML validation |

## 🚀 Getting started

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/ai-devops-toolkit.git
cd ai-devops-toolkit

# 2. Start Ollama and download the default model
ollama serve                         # skip if Ollama already runs as a service/app
ollama pull qwen2.5-coder:7b

# 3. (Optional) install the optional extras
pip install -r requirements.txt

# 4. Run a tool against any project
python tools/generate_dockerfile.py ./my-app
python tools/cicdgen.py ./my-app
```

Every tool supports `--help` for its full list of options.

### Shared configuration

All tools read the same environment variables, so you configure your model once:

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL (local machine, home server or shared GPU box) |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | Model used by default. Override per run with `--model` |

```bash
export OLLAMA_HOST=http://gpu-box:11434
export OLLAMA_MODEL=qwen2.5-coder:14b      # bigger models usually give better results
```

## 🔄 Typical workflow

```text
 your project ──▶ tool reads files ──▶ local LLM drafts artifact ──▶ validation ──▶ diff ──▶ you approve
                                              ▲                          │
                                              └──── errors fed back ─────┘ (automatic retries)
```

A typical day-to-day use:

1. Start a new service and run **`generate_dockerfile.py`** to get a working container image.
2. Run **`cicdgen.py`** to get a pipeline that builds, tests and pushes that image.
3. Keep **`cicdgen.py --watch`** (or a git hook / cron job) running so the pipeline follows the project as it evolves.
4. Review every diff in a pull request, as you would for any other change.

## 🔐 Security and responsible use

- **Review everything.** LLM output can be wrong or incomplete. Read generated files before relying on them.
- **Know where data goes.** Tools send file trees and truncated manifests to the Ollama host you configure. Use a host you trust.
- **Keep secrets out of scanned files.** Never place credentials in files the tools read (`README.md`, `.env.example`, ...). Generated pipelines reference secrets by name only.
- **Generated instructions get executed** when a tool builds an image. Run builds in a trusted, isolated environment.
- **Automatic modes write without asking** (`--yes`, `--watch`). Use them on a branch, keep changes reviewable in git, and check backups.
- **Pin and scan.** Treat generated images and pipelines like any dependency: pin versions and scan them in CI.

## 🧯 Troubleshooting

| Problem | Fix |
|---|---|
| `Cannot reach Ollama at ...` | Start it with `ollama serve`, or set `OLLAMA_HOST` / `--host` |
| `Model '...' is not installed` | `ollama pull <model>` or pick an installed one with `--model` |
| Output is invalid or low quality | Use a larger model, add `--hint` with project details, or raise `--retries` |
| Very slow responses | Use a smaller model, or run Ollama on a machine with a GPU |
| `Docker is not available/running` | Start Docker, or use the tool's `--no-build` option |

Tool-specific problems are covered in each guide under [`docs/`](docs/).

## 🧩 Adding a new tool

New tools are welcome. To keep the toolkit consistent, a tool should:

1. Live in `tools/` as a single, self-contained Python file with a clear module docstring and examples.
2. Use only the standard library where possible, and mark any extra package as optional.
3. Read `OLLAMA_HOST` and `OLLAMA_MODEL` and offer `--model` / `--host`.
4. **Validate model output** with code before writing anything, and retry with the error message on failure.
5. Offer `--dry-run` (or equivalent), show a diff, back up files it replaces, and never overwrite user work silently.
6. Ship a guide in `docs/<tool-name>.md` and add a row to the [tools table](#-tools).

## 🗺️ Roadmap

- 🐳 Dockerfile generation with build-and-fix loop ✅
- 🔄 CI/CD generation with auto-update ✅
- ☸️ Kubernetes manifest and Helm chart generator
- 🏗️ Terraform module generator and reviewer
- 🔍 Log analysis and incident summary helper
- 🛡️ IaC and Dockerfile security review assistant
- 📚 Runbook Q&A over internal documentation (RAG)
- 🔌 Optional OpenAI-compatible endpoint support
- 🧪 Unit tests and CI for the toolkit itself

Ideas and requests are tracked in GitHub Issues.

## 🤝 Contributing

Contributions are welcome: bug reports, new tools, docs and tests.

1. Fork the repository and create a feature branch.
2. Follow the conventions in [Adding a new tool](#-adding-a-new-tool).
3. Test with at least two different models and describe what you tried in the pull request.
4. Open a pull request with a clear description of the change.

## 📄 License

Released under the [MIT License](LICENSE).

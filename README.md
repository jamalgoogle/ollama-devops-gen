# 🤖 ollama-devops-gen

**Local-LLM DevOps generators powered by [Ollama](https://ollama.com).**
Generate and build production-grade **Dockerfiles**, and generate and *auto-update* **CI/CD pipelines**
(GitHub Actions, GitLab CI, Jenkins) for almost any project, without sending your code to a cloud API.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![LLM](https://img.shields.io/badge/LLM-Ollama%20(local)-orange)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## 📌 Overview

Writing a good Dockerfile or pipeline for every new project is repetitive work. This repo contains two
standalone command-line tools that read your project, ask a **local** Ollama model to write the files,
and then **check the result before anything is saved**:

| Tool | Purpose |
|---|---|
| [`generate_dockerfile.py`](generate_dockerfile.py) | Scans a project (or takes a stack name), writes a `Dockerfile` + `.dockerignore`, **builds the image**, and asks the model to fix the Dockerfile if the build fails. |
| [`cicdgen.py`](cicdgen.py) | Creates a CI/CD pipeline for your project and **keeps it up to date** when dependencies, Dockerfile or infrastructure files change. Shows a diff and keeps backups. |

### Why use it

- 🔒 **Private by design.** The model runs on your machine (or your own server). Project files are sent only to the Ollama host you configure.
- 📦 **Zero required dependencies.** Both tools use only the Python standard library (PyYAML is optional).
- ✅ **Validate, then write.** Output is parsed and checked. Invalid answers are rejected and the model is asked again.
- 👀 **You stay in control.** Diffs, confirmation prompts, `--dry-run`, and automatic backups.

---

## 📁 Repository structure

```text
ollama-devops-gen/
├── generate_dockerfile.py   # Dockerfile + .dockerignore generator with build-and-fix loop
├── cicdgen.py               # CI/CD pipeline generator and auto-updater
├── requirements.txt         # Optional: PyYAML for strict YAML validation
├── LICENSE                  # MIT
├── .gitignore
└── README.md
```

---

## ⚙️ Requirements

| Requirement | Needed for |
|---|---|
| Python 3.8+ | Both tools |
| [Ollama](https://ollama.com) running locally (or reachable over the network) | Both tools |
| A pulled model, default `qwen2.5-coder:7b` | Both tools |
| Docker (running) | Only the image **build** step of `generate_dockerfile.py` |
| `pip install pyyaml` | Optional: strict YAML checks in `cicdgen.py` |
| Git | Optional: default-branch detection and `--commit` in `cicdgen.py` |

## 🚀 Quick start

```bash
# 1. Get the code
git clone https://github.com/<your-username>/ollama-devops-gen.git
cd ollama-devops-gen

# 2. Start Ollama and download the default model
ollama serve                      # skip if Ollama already runs as a service/app
ollama pull qwen2.5-coder:7b

# 3. (Optional) strict YAML validation for cicdgen.py
pip install -r requirements.txt

# 4. Generate a Dockerfile for a project, then a pipeline
python generate_dockerfile.py ./my-app
python cicdgen.py ./my-app
```

You can choose another model with `--model` or the `OLLAMA_MODEL` environment variable.
Larger models usually give better results on complex projects.

---

## 🐳 `generate_dockerfile.py`: Dockerfile generator

Input can be **a project folder** or **a stack name**.

- **Project folder:** the tool builds a file tree (up to 3 levels, 120 entries) and reads key manifests
  (for example `package.json`, `requirements.txt`, `pom.xml`, `go.mod`, `Cargo.toml`, `composer.json`,
  `*.csproj`, `Makefile`, `README.md`), each truncated to 2,500 characters. Folders such as `.git`,
  `node_modules`, `venv`, `target` and `dist` are skipped.
- **Stack name** (`"go"`, `"django"`, `"spring boot"`, ...): it writes a generic template for that stack.

### What the model is told to produce

- an official, **pinned** slim/alpine base image (never `latest`)
- a **multi-stage build** for compiled or bundled languages
- dependency files copied first, for **layer caching**
- a **non-root** user in the final stage
- `WORKDIR`, correct `EXPOSE`, exec-form `CMD`/`ENTRYPOINT`
- a `HEALTHCHECK` only when it is sure about a health endpoint
- a matching `.dockerignore`

### Workflow

```text
scan project ─▶ ask model ─▶ validate output ─▶ write Dockerfile (+ .bak backup)
                                                  │
                                         docker build ─▶ success: print run command
                                                  │
                                           failure: send build log back to the model ─▶ retry
```

### Usage

```bash
python generate_dockerfile.py ./my-app                          # scan, generate, build
python generate_dockerfile.py ./my-app --tag my-app:v1          # custom image tag
python generate_dockerfile.py ./my-app --no-build               # generate files only
python generate_dockerfile.py ./my-app --hint "use port 8080"   # extra instructions
python generate_dockerfile.py "FastAPI" --output ./template     # template from a stack name
python generate_dockerfile.py                                   # interactive prompt
```

### Options

| Option | Default | Description |
|---|---|---|
| `target` | *(prompt)* | Project folder **or** language/framework name |
| `-m`, `--model` | `qwen2.5-coder:7b` | Ollama model (env: `OLLAMA_MODEL`) |
| `--host` | `http://localhost:11434` | Ollama server URL (env: `OLLAMA_HOST`) |
| `-t`, `--tag` | `<folder-name>:latest` | Image tag |
| `-o`, `--output` | `./` | Output folder when `target` is a stack name |
| `--no-build` | off | Only generate files, skip `docker build` |
| `--retries` | `3` | How many times to ask the model to fix a failed build |
| `--hint` | empty | Extra instructions for the model |

### Behaviour details

- An existing `Dockerfile` is **backed up** to `Dockerfile.bak` before it is replaced.
- In project mode, an existing `.dockerignore` is **never overwritten**.
- If Docker is not installed or not running, files are still generated and the build is skipped with a warning.
- The model's answer is rejected unless it contains a Dockerfile starting with `FROM` or `ARG`.

---

## 🔄 `cicdgen.py`: CI/CD pipeline generator and auto-updater

Supports **GitHub Actions** (`.github/workflows/*.yml`), **GitLab CI** (`.gitlab-ci.yml`) and
**Jenkins** (`Jenkinsfile`). The platform is auto-detected: an existing `.gitlab-ci.yml` means GitLab,
an existing `Jenkinsfile` means Jenkins, otherwise GitHub.

### Pipeline the model is asked to write

`install/lint → test → build → docker build → push image → deploy`

- Triggers: push to the default branch, pull requests, and tags like `v*`
- Image push only on the **default branch and version tags**, never on pull requests
- Dependency caching, concurrency cancellation, **least-privilege permissions**
- Secrets only by reference (`${{ secrets.NAME }}`, `$VARIABLE`, `credentials('id')`), never hardcoded
- Steps are skipped when the project has no tests or linter, instead of inventing commands
- GitHub Actions limited to a known list (`actions/checkout@v4`, `docker/build-push-action@v6`, ...)

### How auto-update works

1. The tool computes a **fingerprint** of everything that affects a pipeline: dependency manifests and lockfiles,
   `Dockerfile`, Compose files, Kubernetes/Helm/Terraform/Ansible files, and your command-line options.
2. The fingerprint is stored in `.cicdgen.json` inside the target project.
3. **Nothing changed →** the tool exits without calling the model.
4. **Something changed →** the model is asked to **update** the existing pipeline, preserving its structure and custom steps.
   The result is validated, shown as a **unified diff**, and applied only after you confirm (or with `--yes`).
5. Replaced files are copied to `.cicdgen/backups/<timestamp>/`.

> Lockfiles are fingerprinted but **never sent to the model**. If a pipeline file was edited by hand since the last run,
> the tool tells you and instructs the model to keep those edits. Preservation is prompt-based, so **always read the diff**.

### Dependabot (no LLM)

For GitHub projects, `.github/dependabot.yml` is generated **deterministically** from the ecosystems it detects
(`npm`, `pip`, `gomod`, `cargo`, `maven`, `gradle`, `composer`, `bundler`, `docker`) plus `github-actions`,
with a weekly schedule. A hand-edited `dependabot.yml` is left alone. Disable with `--no-dependabot`.

### Validation before writing

| Check | Applies to |
|---|---|
| Output paths must match the platform allow-list | All |
| No tab characters in YAML | GitHub, GitLab |
| Valid YAML with a non-empty mapping (needs PyYAML) | GitHub, GitLab |
| Workflow contains `on:` and `jobs:` | GitHub |
| `stages:` or jobs with `script:` | GitLab |
| Declarative `pipeline { stages { ... } }` | Jenkins |

If validation fails, the model is asked again (see `--retries`).

### Usage

```bash
python cicdgen.py                                              # current folder, auto-detect platform
python cicdgen.py ./my-app --registry dockerhub --deploy kubernetes
python cicdgen.py ./my-app --platform gitlab --yes             # apply without asking
python cicdgen.py ./my-app --dry-run                           # show diffs only
python cicdgen.py ./my-app --hint "run tests with a postgres service"
python cicdgen.py ./my-app --watch --interval 60               # keep the pipeline up to date
python cicdgen.py ./my-app --commit                            # git commit the changed files
```

### Options

| Option | Default | Description |
|---|---|---|
| `project` | `.` | Project folder |
| `-m`, `--model` | `qwen2.5-coder:7b` | Ollama model (env: `OLLAMA_MODEL`) |
| `--host` | `http://localhost:11434` | Ollama server URL (env: `OLLAMA_HOST`) |
| `--platform` | `auto` | `auto`, `github`, `gitlab`, `jenkins` |
| `--registry` | `ghcr` | `ghcr`, `dockerhub`, `ecr`, `gcr`, `none` |
| `--deploy` | `none` | `none`, `kubernetes`, `ssh`, `ecs`, `helm` |
| `--branch` | current git branch, else `main` | Default branch used in triggers |
| `--hint` | empty | Extra instructions for the model |
| `--watch` | off | Keep running and update when inputs change (applies changes without asking) |
| `--interval` | `30` | Seconds between checks in `--watch` mode |
| `--force` | off | Regenerate even if nothing changed |
| `--dry-run` | off | Show diffs, write nothing |
| `-y`, `--yes` | off | Apply without confirmation |
| `--commit` | off | `git commit` the changed pipeline files |
| `--no-dependabot` | off | Do not manage `.github/dependabot.yml` |
| `--retries` | `2` | Re-asks when the model output is invalid |

### Files created in your project

| Path | Purpose |
|---|---|
| `.github/workflows/*.yml`, `.gitlab-ci.yml` or `Jenkinsfile` | The pipeline |
| `.github/dependabot.yml` | Dependency update config (GitHub only) |
| `.cicdgen.json` | Fingerprint and bookkeeping for auto-update |
| `.cicdgen/backups/<timestamp>/` | Copies of replaced files |

After a run, the tool prints a **to-do list of secrets** referenced by the pipeline (for example `DOCKERHUB_TOKEN`)
that you must add in your CI settings.

### Run it on a schedule

```bash
# Git hook (.git/hooks/pre-push): refresh the pipeline before every push
python /path/to/cicdgen.py . --yes

# Cron: check every night at 02:00
0 2 * * * cd /path/to/project && python /path/to/cicdgen.py . --yes --commit
```

---

## 🔐 Security notes

- **Review everything.** LLM output can be wrong. Read the Dockerfile and pipeline before you rely on them.
- **Data stays local** only if `--host` points to a machine you trust. Manifest snippets and the file tree are sent to that host.
- **Do not put secrets in files the tools read** (for example `.env.example`, `README.md`).
- **Building runs generated instructions.** `generate_dockerfile.py` runs `docker build` on model output. Use a trusted, isolated environment.
- **`--watch` and `--yes` write without asking.** Use them on a branch, keep `--commit` for reviewable history, and check backups.

## 🧯 Troubleshooting

| Problem | Fix |
|---|---|
| `Cannot reach Ollama at ...` | Start it with `ollama serve`, or set `--host` / `OLLAMA_HOST` |
| `Model '...' is not installed` | `ollama pull <model>` or choose an installed one with `--model` |
| `Could not get a valid ... from the model` | Use a bigger model (`--model`), add `--hint`, or raise `--retries` |
| Docker build never succeeds | Read the last log lines, fix manually, or try another model |
| `[warn] Docker is not available/running` | Start Docker, or use `--no-build` |
| Pipeline uses a command your project lacks | Add `--hint` describing your real scripts, then review the diff |

## 🗺️ Roadmap ideas

- Optional OpenAI-compatible endpoint support
- Dry-run linting with `hadolint` and `actionlint`
- More platforms (Azure Pipelines, Bitbucket Pipelines, CircleCI)
- Unit tests for parsing and validation helpers

## 🤝 Contributing

Issues and pull requests are welcome. Keep the tools dependency-free and test with at least two different models.

## 📄 License

Released under the [MIT License](LICENSE).

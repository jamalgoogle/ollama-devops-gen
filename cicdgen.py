#!/usr/bin/env python3
"""
cicdgen.py - Auto-generate AND auto-update a CI/CD pipeline using a local Ollama model.

What it manages
  * GitHub Actions workflows (.github/workflows/*.yml), GitLab CI (.gitlab-ci.yml) or Jenkinsfile
  * .github/dependabot.yml (built from the ecosystems it detects, no LLM needed)

How "auto-update" works
  The script fingerprints everything that affects a pipeline (dependency manifests, Dockerfile,
  compose/k8s/helm/terraform files, your options) and stores it in .cicdgen.json. On every run:
    - nothing changed  -> does nothing
    - something changed -> asks the model to UPDATE the existing pipeline (keeping your manual edits),
                           validates it, shows a diff, backs up old files, writes the new ones.
  Use --watch to keep doing this forever, or run it from a git hook / scheduled job.

Examples
  python cicdgen.py                          # current folder, auto-detect platform
  python cicdgen.py ./my-app --registry dockerhub --deploy kubernetes
  python cicdgen.py ./my-app --platform gitlab --yes
  python cicdgen.py ./my-app --watch --interval 60
  python cicdgen.py ./my-app --dry-run       # only show what would change

Requirements: Python 3.8+, Ollama running locally. Optional: `pip install pyyaml` for strict YAML checks.
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import yaml  # optional
except ImportError:
    yaml = None

DEFAULT_MODEL = "qwen2.5-coder:7b"
STATE_FILE = ".cicdgen.json"
BACKUP_DIR = ".cicdgen/backups"

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env", "target", "build", "dist",
    ".idea", ".vscode", "vendor", ".next", ".nuxt", ".gradle", "bin", "obj", ".terraform",
    ".pytest_cache", ".mypy_cache", ".cicdgen",
}
MANIFESTS = [
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "requirements.txt",
    "pyproject.toml", "Pipfile", "setup.py", "pom.xml", "build.gradle", "build.gradle.kts",
    "go.mod", "Cargo.toml", "composer.json", "Gemfile", "mix.exs", "pubspec.yaml", "tsconfig.json",
    "Makefile", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "tox.ini", "pytest.ini",
    ".eslintrc.json", ".eslintrc.js", "README.md",
]
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}  # fingerprint only, never sent to model
MANIFEST_GLOBS = ["*.csproj", "*.sln", "*.sbt"]
INFRA_DIRS = {"k8s", "kubernetes", "helm", "charts", "deploy", "manifests", "terraform", "infra", "ansible"}
INFRA_NAMES = {"Chart.yaml", "kustomization.yaml", "skaffold.yaml", "serverless.yml", "appspec.yml"}
ECOSYSTEMS = {
    "package.json": "npm", "requirements.txt": "pip", "pyproject.toml": "pip", "Pipfile": "pip",
    "go.mod": "gomod", "Cargo.toml": "cargo", "pom.xml": "maven", "build.gradle": "gradle",
    "build.gradle.kts": "gradle", "composer.json": "composer", "Gemfile": "bundler", "Dockerfile": "docker",
}
ALLOWED_PATHS = {
    "github": re.compile(r"^\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml$"),
    "gitlab": re.compile(r"^\.gitlab-ci\.yml$"),
    "jenkins": re.compile(r"^Jenkinsfile$"),
}
MAX_FILE_CHARS = 2500

SYSTEM_PROMPT = """You are a senior DevOps/platform engineer who writes secure, production-grade CI/CD pipelines.

You receive: project info, the target CI platform, options, and (maybe) the CURRENT pipeline files.
If current pipeline files are given, UPDATE them: keep their structure, names, and any custom steps,
and change only what the project info requires. Otherwise create a new pipeline.

Pipeline requirements:
- Stages: install/lint -> test -> build -> (if a Dockerfile exists) docker build -> push image
  (only on the default branch and version tags, never on pull requests) -> deploy (only if requested).
- Triggers: push to the default branch, pull requests, and tags like v*.
- Cache dependencies. Cancel superseded runs (concurrency). Use least-privilege permissions.
- Never hardcode secrets or tokens. Reference them by name: ${{ secrets.NAME }} (GitHub),
  $VARIABLE (GitLab), credentials('id') (Jenkins).
- Only use commands/scripts that really exist in the project (check package.json scripts, Makefile, etc.).
  If tests/lint tools are not configured, skip that step instead of inventing one.
- GitHub Actions: use these well-known actions at these major versions:
  actions/checkout@v4, actions/setup-node@v4, actions/setup-python@v5, actions/setup-go@v4,
  actions/setup-java@v4, docker/setup-buildx-action@v3, docker/login-action@v3,
  docker/metadata-action@v5, docker/build-push-action@v6, aws-actions/configure-aws-credentials@v4.
  Do not invent other actions.

OUTPUT FORMAT (strict, nothing else - no explanations):
### FILE: <relative path>
```yaml
<full file content>
```
Repeat the block for every file. Paths allowed: .github/workflows/*.yml, .gitlab-ci.yml, Jenkinsfile.
"""


# --------------------------------------------------------------------------- #
# Ollama
# --------------------------------------------------------------------------- #
def normalize_host(host):
    host = host.strip().rstrip("/")
    return host if host.startswith(("http://", "https://")) else "http://" + host


def check_ollama(host, model):
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=10) as r:
            models = [m["name"] for m in json.load(r).get("models", [])]
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        sys.exit(f"[error] Cannot reach Ollama at {host}. Start it with: ollama serve")
    if model not in models and model.split(":")[0] not in {m.split(":")[0] for m in models}:
        sys.exit(f"[error] Model '{model}' not installed (have: {', '.join(models) or 'none'}). "
                 f"Run: ollama pull {model}")


def ollama_chat(host, model, messages, temperature=0.1):
    payload = {"model": model, "messages": messages, "stream": True,
               "options": {"temperature": temperature, "num_ctx": 12288}}
    req = urllib.request.Request(f"{host}/api/chat", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    out = []
    try:
        with urllib.request.urlopen(req, timeout=1200) as resp:
            for raw in resp:
                raw = raw.strip()
                if not raw:
                    continue
                chunk = json.loads(raw)
                if "error" in chunk:
                    raise RuntimeError(chunk["error"])
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    out.append(piece)
                    print(piece, end="", flush=True)
                if chunk.get("done"):
                    break
    except urllib.error.URLError as e:
        sys.exit(f"[error] Ollama request failed: {e}")
    print()
    return "".join(out)


# --------------------------------------------------------------------------- #
# Project inspection
# --------------------------------------------------------------------------- #
def sha(text):
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def read(path, limit=None):
    try:
        t = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return t[:limit] + "\n... (truncated)" if limit and len(t) > limit else t


def tree(root, max_entries=100, max_depth=3):
    lines, base = [], len(root.parts)
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d not in IGNORE_DIRS)
        depth = len(Path(dp).parts) - base
        if depth > max_depth:
            dn[:] = []
            continue
        rel = Path(dp).relative_to(root)
        for f in sorted(fn):
            lines.append(str(rel / f) if str(rel) != "." else f)
        if len(lines) >= max_entries:
            lines.append("... (truncated)")
            break
    return "\n".join(lines)


def manifest_files(root):
    found = [root / n for n in MANIFESTS if (root / n).is_file()]
    for g in MANIFEST_GLOBS:
        found += sorted(root.glob(g))[:2]
    return found


def infra_files(root):
    found = []
    base = len(root.parts)
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in IGNORE_DIRS]
        if len(Path(dp).parts) - base > 4:
            dn[:] = []
            continue
        in_infra = any(p in INFRA_DIRS for p in Path(dp).relative_to(root).parts)
        for f in fn:
            if f in INFRA_NAMES or f.endswith(".tf") or (in_infra and f.endswith((".yml", ".yaml"))):
                found.append(Path(dp) / f)
    return sorted(found)[:40]


def detect_platform(root, wanted):
    if wanted != "auto":
        return wanted
    if (root / ".gitlab-ci.yml").exists():
        return "gitlab"
    if (root / "Jenkinsfile").exists():
        return "jenkins"
    return "github"


def existing_pipeline(root, platform):
    if platform == "github":
        d = root / ".github" / "workflows"
        paths = sorted(list(d.glob("*.yml")) + list(d.glob("*.yaml"))) if d.is_dir() else []
    elif platform == "gitlab":
        paths = [root / ".gitlab-ci.yml"] if (root / ".gitlab-ci.yml").is_file() else []
    else:
        paths = [root / "Jenkinsfile"] if (root / "Jenkinsfile").is_file() else []
    return {p.relative_to(root).as_posix(): read(p) for p in paths}


def default_branch(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "symbolic-ref", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "main"


def fingerprint(root, platform, args):
    h = [platform, args.registry, args.deploy, args.branch or "", args.hint]
    for p in manifest_files(root):
        h.append(p.name + sha(read(p)))
    for p in infra_files(root):
        h.append(p.relative_to(root).as_posix() + sha(read(p, 100000)))
    for n in LOCKFILES:
        if (root / n).is_file():
            h.append(n + sha(read(root / n, 2_000_000)))
    return sha("|".join(h))


def describe(root, platform, args, existing):
    parts = [f"Project folder: {root.name}", f"CI platform: {platform}",
             f"Default branch: {args.branch}", f"Container registry: {args.registry}",
             f"Deploy target: {args.deploy}"]
    if args.hint:
        parts.append(f"Extra requirements: {args.hint}")
    parts += ["", "FILE TREE:", tree(root), ""]
    for p in manifest_files(root):
        if p.name in LOCKFILES:
            continue
        parts += [f"--- {p.name} ---", read(p, MAX_FILE_CHARS), ""]
    infra = infra_files(root)
    if infra:
        parts += ["INFRA FILES: " + ", ".join(p.relative_to(root).as_posix() for p in infra), ""]
    if not (root / "Dockerfile").exists():
        parts += ["NOTE: there is no Dockerfile, so skip docker build/push steps.", ""]
    if existing:
        parts.append("CURRENT PIPELINE FILES (update these, preserve custom steps):")
        for path, content in existing.items():
            parts += [f"### FILE: {path}", "```yaml", content.rstrip(), "```", ""]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Parsing and validation
# --------------------------------------------------------------------------- #
def parse_and_validate(reply, platform):
    files = {}
    for m in re.finditer(r"###\s*FILE:\s*`?([^\s`]+)`?\s*\n```[^\n]*\n(.*?)```", reply, re.S):
        path, content = m.group(1).strip().lstrip("./"), m.group(2).strip() + "\n"
        if not ALLOWED_PATHS[platform].match(path):
            return None, f"Path '{path}' is not allowed for {platform}."
        files[path] = content
    if not files:
        return None, "No '### FILE: <path>' blocks followed by fenced code were found."
    for path, content in files.items():
        err = validate(path, content, platform)
        if err:
            return None, f"{path}: {err}"
    return files, None


def validate(path, content, platform):
    if "\t" in content and platform != "jenkins":
        return "contains tab characters (YAML requires spaces)."
    if platform == "jenkins":
        if "pipeline" not in content or "stages" not in content:
            return "Jenkinsfile must define a declarative `pipeline { stages { ... } }`."
        return None
    if yaml:
        try:
            doc = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return f"invalid YAML: {e}"
        if not isinstance(doc, dict) or not doc:
            return "YAML root must be a non-empty mapping."
        if platform == "github" and not (("on" in doc or True in doc) and "jobs" in doc):
            return "GitHub workflow needs both `on:` and `jobs:`."
        if platform == "gitlab" and "stages" not in doc and not any(isinstance(v, dict) and "script" in v for v in doc.values()):
            return "GitLab CI needs `stages:` or jobs with `script:`."
    else:
        if platform == "github" and ("jobs:" not in content or not re.search(r"^on:", content, re.M)):
            return "GitHub workflow needs `on:` and `jobs:`."
    return None


# --------------------------------------------------------------------------- #
# Deterministic extras (no LLM)
# --------------------------------------------------------------------------- #
def dependabot_yaml(root):
    ecos = []
    for name, eco in ECOSYSTEMS.items():
        if (root / name).is_file() and eco not in ecos:
            ecos.append(eco)
    ecos.insert(0, "github-actions")
    blocks = ["version: 2", "updates:"]
    for eco in ecos:
        blocks += [f'  - package-ecosystem: "{eco}"', '    directory: "/"',
                   "    schedule:", '      interval: "weekly"']
    return "\n".join(blocks) + "\n"


# --------------------------------------------------------------------------- #
# State, diff, writing
# --------------------------------------------------------------------------- #
def load_state(root):
    try:
        return json.loads((root / STATE_FILE).read_text())
    except (OSError, ValueError):
        return {}


def save_state(root, fp, platform, model, written):
    state = load_state(root)
    files = state.get("files", {})
    files.update({p: sha(c) for p, c in written.items()})
    state.update({"fingerprint": fp, "platform": platform, "model": model, "files": files,
                  "updated": datetime.now().isoformat(timespec="seconds")})
    (root / STATE_FILE).write_text(json.dumps(state, indent=2) + "\n")


def show_diff(path, old, new):
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                     f"a/{path}", f"b/{path}", lineterm=""))
    print(f"\n----- {path} {'(new file)' if not old else ''}")
    for line in diff[:200]:
        print(line)
    if len(diff) > 200:
        print(f"... ({len(diff) - 200} more lines)")


def apply_files(root, files, backup_ts):
    for path, content in files.items():
        target = root / path
        if target.exists():
            b = root / BACKUP_DIR / backup_ts / path
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, b)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"[ok] Wrote {path}")


def required_secrets(files):
    names = set()
    for content in files.values():
        names |= set(re.findall(r"secrets\.([A-Za-z0-9_]+)", content))
        names |= set(re.findall(r"credentials\(['\"]([^'\"]+)['\"]\)", content))
    names.discard("GITHUB_TOKEN")
    return sorted(names)


def git_commit(root, paths):
    try:
        subprocess.run(["git", "-C", str(root), "add", *paths], check=True, capture_output=True)
        r = subprocess.run(["git", "-C", str(root), "commit", "-m", "ci: update pipeline (cicdgen)"],
                           capture_output=True, text=True)
        print("[ok] Committed." if r.returncode == 0 else f"[info] Nothing committed: {r.stdout.strip() or r.stderr.strip()}")
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[warn] git commit failed: {e}")


# --------------------------------------------------------------------------- #
# One update cycle
# --------------------------------------------------------------------------- #
def run_once(args, root, host):
    platform = detect_platform(root, args.platform)
    fp = fingerprint(root, platform, args)
    state = load_state(root)
    existing = existing_pipeline(root, platform)

    if not args.force and existing and state.get("fingerprint") == fp and state.get("platform") == platform:
        print(f"[ok] {datetime.now():%H:%M:%S} Pipeline inputs unchanged - nothing to update.")
        return False

    managed = state.get("files", {})
    for path, content in existing.items():
        if path in managed and managed[path] != sha(content):
            print(f"[info] {path} was edited manually since the last run - the model is told to preserve those edits.")

    print(f"[info] Platform: {platform} | model: {args.model} | "
          f"{'updating existing pipeline' if existing else 'creating new pipeline'}")
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Write/update the CI/CD pipeline.\n\n" + describe(root, platform, args, existing)}]

    files = None
    for attempt in range(1, args.retries + 2):
        print(f"\n[info] Asking the model (attempt {attempt}/{args.retries + 1})...\n")
        reply = ollama_chat(host, args.model, messages)
        messages.append({"role": "assistant", "content": reply})
        files, err = parse_and_validate(reply, platform)
        if files:
            break
        print(f"\n[warn] Rejected: {err}")
        messages.append({"role": "user", "content":
                         f"Problem: {err}\nReply again with ALL files in the required '### FILE:' format and nothing else."})
    if not files:
        print("[error] Could not get a valid pipeline from the model. Try a bigger model with --model.")
        return False

    if platform == "github" and not args.no_dependabot:
        dep_path = ".github/dependabot.yml"
        dep_old = read(root / dep_path) if (root / dep_path).exists() else ""
        if not dep_old or managed.get(dep_path) == sha(dep_old):
            files[dep_path] = dependabot_yaml(root)
        else:
            print(f"[info] {dep_path} is user-managed - leaving it alone.")

    changes = {p: c for p, c in files.items()
               if c != (read(root / p) if (root / p).exists() else None)}
    if not changes:
        print("[ok] Model output matches the current files - no changes.")
        save_state(root, fp, platform, args.model, {})
        return False

    for p, c in changes.items():
        show_diff(p, read(root / p) if (root / p).exists() else "", c)

    if args.dry_run:
        print("\n[dry-run] No files written.")
        return False
    if not args.yes and input("\nApply these changes? [y/N] ").strip().lower() != "y":
        print("[info] Skipped.")
        return False

    apply_files(root, changes, datetime.now().strftime("%Y%m%d-%H%M%S"))
    save_state(root, fp, platform, args.model, files)

    secrets = required_secrets(files)
    if secrets:
        print("\n[todo] Add these secrets/credentials in your CI settings: " + ", ".join(secrets))
    if args.commit:
        git_commit(root, list(changes) + [STATE_FILE])
    return True


def main():
    ap = argparse.ArgumentParser(description="Generate and auto-update a CI/CD pipeline with Ollama.")
    ap.add_argument("project", nargs="?", default=".", help="Project folder (default: current folder)")
    ap.add_argument("-m", "--model", default=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL))
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    ap.add_argument("--platform", choices=["auto", "github", "gitlab", "jenkins"], default="auto")
    ap.add_argument("--registry", choices=["ghcr", "dockerhub", "ecr", "gcr", "none"], default="ghcr")
    ap.add_argument("--deploy", choices=["none", "kubernetes", "ssh", "ecs", "helm"], default="none")
    ap.add_argument("--branch", help="Default branch (default: current git branch or 'main')")
    ap.add_argument("--hint", default="", help="Extra instructions, e.g. 'run tests with a postgres service'")
    ap.add_argument("--watch", action="store_true", help="Keep running and update the pipeline when inputs change")
    ap.add_argument("--interval", type=int, default=30, help="Seconds between checks in --watch mode")
    ap.add_argument("--force", action="store_true", help="Regenerate even if nothing changed")
    ap.add_argument("--dry-run", action="store_true", help="Show diffs only, write nothing")
    ap.add_argument("-y", "--yes", action="store_true", help="Apply without asking")
    ap.add_argument("--commit", action="store_true", help="git commit the changed pipeline files")
    ap.add_argument("--no-dependabot", action="store_true", help="Do not manage .github/dependabot.yml")
    ap.add_argument("--retries", type=int, default=2, help="Re-asks when the output is invalid (default: 2)")
    args = ap.parse_args()

    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"[error] '{args.project}' is not a folder.")
    args.branch = args.branch or default_branch(root)
    host = normalize_host(args.host)
    check_ollama(host, args.model)

    if not args.watch:
        run_once(args, root, host)
        return

    args.yes = True
    print(f"[watch] Checking {root} every {args.interval}s (Ctrl+C to stop). Changes are applied automatically; "
          f"backups go to {BACKUP_DIR}/")
    while True:
        try:
            run_once(args, root, host)
        except Exception as e:  # keep the watcher alive
            print(f"[error] {e}")
        args.force = False
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\n[abort] Stopped.")
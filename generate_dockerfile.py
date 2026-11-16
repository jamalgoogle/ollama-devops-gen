#!/usr/bin/env python3
"""
dockergen.py - Generate (and build) a Docker image for ANY language/framework
using a local Ollama model.

Input can be:
  * a path to a project folder  -> the script scans it and writes a tailored Dockerfile
  * a stack name ("go", "spring boot", "django", "laravel"...) -> writes a generic template

Examples:
  python dockergen.py ./my-app
  python dockergen.py ./my-app --model qwen2.5-coder:7b --tag my-app:v1
  python dockergen.py "FastAPI" --output ./template
  python dockergen.py                      # interactive prompt

Requirements: Python 3.8+, Ollama running locally, Docker (only for building).
No third-party Python packages are needed.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "qwen2.5-coder:7b"
IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env", "target",
    "build", "dist", ".idea", ".vscode", "vendor", ".next", ".nuxt", ".gradle",
    "bin", "obj", ".terraform", ".pytest_cache", ".mypy_cache",
}
# Files that reveal language / framework / dependencies / entrypoint.
MANIFESTS = [
    "package.json", "requirements.txt", "pyproject.toml", "Pipfile", "setup.py",
    "manage.py", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "go.mod", "Cargo.toml", "composer.json", "Gemfile", "mix.exs", "pubspec.yaml",
    "deno.json", "bun.lockb", "tsconfig.json", "next.config.js", "vite.config.js",
    "vite.config.ts", "angular.json", "Makefile", "Procfile", "docker-compose.yml",
    "README.md", ".env.example",
]
MANIFEST_GLOBS = ["*.csproj", "*.fsproj", "*.sln", "*.cabal", "*.sbt"]

MAX_FILE_CHARS = 2500
MAX_TREE_ENTRIES = 120

SYSTEM_PROMPT = """You are a senior DevOps engineer who writes production-grade Dockerfiles.

Given information about a project (or only a language/framework name), produce:
1. A Dockerfile
2. A .dockerignore

Rules for the Dockerfile:
- Use an official, specific, slim/alpine base image tag (never `latest`).
- Use a multi-stage build whenever the language compiles or bundles (Go, Rust, Java, .NET, C/C++, Node frontends, etc.).
- Copy dependency manifests first and install dependencies BEFORE copying the rest of the source (layer caching).
- Run as a non-root user in the final stage.
- Set WORKDIR, EXPOSE the correct port, and use exec-form CMD/ENTRYPOINT (JSON array).
- Add a HEALTHCHECK only if you are confident about a health endpoint.
- Only use commands and files that really exist in the project. If something is unknown, choose the most common convention for that framework.
- No comments that are longer than one short line.

OUTPUT FORMAT (strict): reply with exactly two fenced code blocks and NOTHING else:
```dockerfile
...
```
```dockerignore
...
```
"""


# --------------------------------------------------------------------------- #
# Ollama helpers
# --------------------------------------------------------------------------- #
def normalize_host(host: str) -> str:
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host


def ollama_models(host: str):
    with urllib.request.urlopen(f"{host}/api/tags", timeout=10) as resp:
        data = json.load(resp)
    return [m["name"] for m in data.get("models", [])]


def check_ollama(host: str, model: str):
    try:
        models = ollama_models(host)
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        sys.exit(
            f"[error] Cannot reach Ollama at {host}.\n"
            "        Start it with:  ollama serve"
        )
    names = {m.split(":")[0] for m in models} | set(models)
    if model not in names and model.split(":")[0] not in names:
        have = ", ".join(models) or "none"
        sys.exit(
            f"[error] Model '{model}' is not installed (installed: {have}).\n"
            f"        Pull it with:  ollama pull {model}"
        )


def ollama_chat(host: str, model: str, messages: list, temperature: float = 0.2) -> str:
    """Stream a chat completion from Ollama and return the full text."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temperature, "num_ctx": 8192},
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    parts = []
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            for raw in resp:
                raw = raw.strip()
                if not raw:
                    continue
                chunk = json.loads(raw)
                if "error" in chunk:
                    raise RuntimeError(chunk["error"])
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    parts.append(piece)
                    print(piece, end="", flush=True)
                if chunk.get("done"):
                    break
    except urllib.error.URLError as e:
        sys.exit(f"[error] Ollama request failed: {e}")
    print()
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Project scanning
# --------------------------------------------------------------------------- #
def build_tree(root: Path) -> str:
    lines = []
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS)
        depth = len(Path(dirpath).parts) - root_depth
        if depth > 3:
            dirnames[:] = []
            continue
        rel = Path(dirpath).relative_to(root)
        if str(rel) != ".":
            lines.append(f"{rel}/")
        for f in sorted(filenames):
            lines.append(str(rel / f) if str(rel) != "." else f)
        if len(lines) >= MAX_TREE_ENTRIES:
            lines.append("... (truncated)")
            break
    return "\n".join(lines[:MAX_TREE_ENTRIES + 1])


def read_snippet(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS] + "\n... (truncated)"
    return text


def collect_manifests(root: Path):
    found = []
    for name in MANIFESTS:
        p = root / name
        if p.is_file():
            found.append(p)
    for pattern in MANIFEST_GLOBS:
        found.extend(sorted(root.glob(pattern))[:2])
    return found


def describe_project(root: Path) -> str:
    parts = [f"Project folder name: {root.name}", "", "FILE TREE:", build_tree(root), ""]
    for p in collect_manifests(root):
        parts.append(f"--- {p.name} ---")
        parts.append(read_snippet(p))
        parts.append("")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Parsing the model output
# --------------------------------------------------------------------------- #
def extract_blocks(text: str):
    df = re.search(r"```(?:dockerfile|Dockerfile)[^\n]*\n(.*?)```", text, re.S)
    di = re.search(r"```(?:dockerignore|ignore)[^\n]*\n(.*?)```", text, re.S)
    dockerfile = df.group(1).strip() + "\n" if df else None
    dockerignore = di.group(1).strip() + "\n" if di else None
    if dockerfile is None:
        # fallback: any fenced block that starts with FROM/ARG
        for m in re.finditer(r"```[^\n]*\n(.*?)```", text, re.S):
            body = m.group(1).strip()
            if re.match(r"(?i)^(#.*\n)*\s*(FROM|ARG)\b", body):
                dockerfile = body + "\n"
                break
    return dockerfile, dockerignore


def looks_valid(dockerfile) -> bool:
    if not dockerfile:
        return False
    for line in dockerfile.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        return s.upper().startswith(("FROM", "ARG"))
    return False


def detect_port(dockerfile: str):
    m = re.search(r"(?im)^\s*EXPOSE\s+(\d+)", dockerfile)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# Docker helpers
# --------------------------------------------------------------------------- #
def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=30)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def docker_build(context: Path, dockerfile: Path, tag: str):
    """Run docker build, stream output, return (ok, tail_of_log)."""
    cmd = ["docker", "build", "-t", tag, "-f", str(dockerfile), str(context)]
    print(f"\n$ {' '.join(cmd)}\n")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in proc.stdout:
        print(line, end="")
        tail.append(line)
        tail = tail[-60:]
    proc.wait()
    return proc.returncode == 0, "".join(tail)


def write_with_backup(path: Path, content: str):
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        shutil.copy2(path, backup)
        print(f"[info] Existing {path.name} backed up to {backup.name}")
    path.write_text(content, encoding="utf-8")
    print(f"[ok] Wrote {path}")


def safe_tag(name: str) -> str:
    name = re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-.")
    return (name or "app") + ":latest"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="Generate a Dockerfile (and build the image) for any language/framework using Ollama."
    )
    ap.add_argument("target", nargs="?",
                    help="Path to a project folder OR a language/framework name (e.g. 'go', 'django')")
    ap.add_argument("-m", "--model", default=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
                    help=f"Ollama model (default: {DEFAULT_MODEL})")
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
                    help="Ollama server URL")
    ap.add_argument("-t", "--tag", help="Image tag (default: <folder-name>:latest)")
    ap.add_argument("-o", "--output", help="Where to write files when TARGET is a stack name (default: ./)")
    ap.add_argument("--no-build", action="store_true", help="Only generate the files, do not run docker build")
    ap.add_argument("--retries", type=int, default=3,
                    help="Times to ask the model to fix a failed build (default: 3)")
    ap.add_argument("--hint", default="", help="Extra instructions for the model (e.g. 'use port 8080')")
    args = ap.parse_args()

    target = args.target or input("Project path or language/framework: ").strip()
    if not target:
        sys.exit("[error] Nothing to do - give a project path or a language/framework name.")

    host = normalize_host(args.host)
    check_ollama(host, args.model)

    target_path = Path(target).expanduser()
    project_mode = target_path.is_dir()

    if project_mode:
        root = target_path.resolve()
        print(f"[info] Scanning project: {root}")
        user_prompt = "Write a Dockerfile and .dockerignore for this project.\n\n" + describe_project(root)
        out_dir = root
        tag = args.tag or safe_tag(root.name)
    else:
        print(f"[info] No such folder - treating '{target}' as a language/framework name.")
        user_prompt = (
            f"Write a generic, production-ready Dockerfile and .dockerignore for a typical "
            f"'{target}' application. Assume standard project layout and conventions for it."
        )
        out_dir = Path(args.output or ".").expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = args.tag or safe_tag(target)

    if args.hint:
        user_prompt += f"\n\nExtra requirements: {args.hint}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    can_build = project_mode and not args.no_build
    if can_build and not docker_available():
        print("[warn] Docker is not available/running - files will be generated but not built.")
        can_build = False

    dockerfile_path = out_dir / "Dockerfile"
    dockerignore_path = out_dir / ".dockerignore"
    dockerfile = None
    attempts = args.retries + 1 if can_build else 1

    for attempt in range(1, attempts + 1):
        print(f"\n[info] Asking {args.model} (attempt {attempt}/{attempts})...\n")
        reply = ollama_chat(host, args.model, messages)
        messages.append({"role": "assistant", "content": reply})

        dockerfile, dockerignore = extract_blocks(reply)
        if not looks_valid(dockerfile):
            print("[warn] Model output did not contain a valid Dockerfile.")
            messages.append({
                "role": "user",
                "content": "Your reply had no valid Dockerfile. Reply again with ONLY the two fenced "
                           "blocks: ```dockerfile and ```dockerignore.",
            })
            dockerfile = None
            continue

        write_with_backup(dockerfile_path, dockerfile)
        if dockerignore and project_mode and not dockerignore_path.exists():
            dockerignore_path.write_text(dockerignore, encoding="utf-8")
            print(f"[ok] Wrote {dockerignore_path}")
        elif dockerignore and not project_mode:
            write_with_backup(dockerignore_path, dockerignore)

        if not can_build:
            break

        ok, log_tail = docker_build(out_dir, dockerfile_path, tag)
        if ok:
            print(f"\n[ok] Image built: {tag}")
            port = detect_port(dockerfile) or "8080"
            print(f"     Run it with:  docker run --rm -p {port}:{port} {tag}")
            return
        if attempt < attempts:
            print("\n[warn] Build failed - sending the error back to the model to fix it...")
            messages.append({
                "role": "user",
                "content": "docker build failed with this output (last lines):\n\n"
                           f"{log_tail}\n\nFix the Dockerfile. Reply again with ONLY the two fenced "
                           "blocks: ```dockerfile and ```dockerignore.",
            })

    if dockerfile is None:
        sys.exit("[error] Could not get a valid Dockerfile from the model. Try a bigger model with --model.")
    if can_build:
        sys.exit(f"[error] Build still failing after {attempts} attempts. "
                 f"Review {dockerfile_path} and fix it manually, or try another --model.")

    print("\n[done] Dockerfile generated.")
    if project_mode:
        print(f"       Build it with:  docker build -t {tag} {out_dir}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\n[abort] Cancelled.")












# import ollama   # Python helper to talk to the Ollama server on your computer

# # The model name MUST be the same as the one you downloaded with "ollama pull".
# MODEL = "llama3.1:8b"   # FIX: README said llama3.2:1b, so now we use one name only

# # The prompt = the instruction we send to the AI. {language} is filled later.
# PROMPT = """
# ONLY Generate an ideal Dockerfile for {language} with best practices. Do not provide any description
# Include:
# - Base image
# - Installing dependencies
# - Setting working directory
# - Adding source code
# - Running the application
# """

# def generate_dockerfile(language):
#     # Send one message (role "user") to the local model and wait for the answer.
#     response = ollama.chat(
#         model=MODEL,
#         messages=[{"role": "user", "content": PROMPT.format(language=language)}],
#     )
#     # The text answer is inside response["message"]["content"].
#     return response["message"]["content"]

# if __name__ == "__main__":                      # runs only when you start this file
#     language = input("Enter the programming language: ")   # ask the user
#     dockerfile = generate_dockerfile(language)              # call the AI
#     print("\nGenerated Dockerfile:\n")
#     print(dockerfile)                                       # show the result

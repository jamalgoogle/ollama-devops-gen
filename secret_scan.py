import os, re, sys

# Patterns that look like secrets. (name, regular expression)
PATTERNS = [
    ("AWS access key",   re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token",     re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("Private key",      re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Hardcoded secret", re.compile(r"""(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['"][^'"]{8,}['"]""")),
]
SKIP_DIRS = {".git", "node_modules", "venv", "__pycache__"}   # folders we do not scan

def mask(text):                          # show only the start: never print a full secret
    return text[:4] + "*" * 8

def scan(root):
    findings = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]      # skip big/useless folders
        for name in files:
            path = os.path.join(folder, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for number, line in enumerate(f, start=1):   # line numbers start at 1
                        for label, pattern in PATTERNS:
                            m = pattern.search(line)
                            if m:
                                findings.append((path, number, label, mask(m.group(0))))
            except (UnicodeDecodeError, PermissionError):
                continue                                         # binary or locked file
    return findings

if __name__ == "__main__":
    results = scan(sys.argv[1] if len(sys.argv) > 1 else ".")
    for path, number, label, preview in results:
        print(f"⚠️  {path}:{number}  {label}  ({preview})")
    print(f"\n{len(results)} possible secret(s) found.")
    # Idea: send ONLY the label + file name to an LLM to explain the risk.
    # NEVER send the secret value itself to a public AI tool.
    sys.exit(1 if results else 0)          # exit 1 makes the CI/CD pipeline fail

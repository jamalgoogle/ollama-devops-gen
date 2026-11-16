import os, re
import requests                                   # call the LLM API
from flask import Flask, jsonify, request         # tiny web server
from kubernetes import client, config             # official Kubernetes Python library

app = Flask(__name__)

# ---------- Settings come from environment variables (set in Kubernetes) ----------
PROVIDER = os.getenv("LLM_PROVIDER", "gemini")                    # "gemini" or "ollama"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")      # check the current name
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# ---------- Kubernetes client ----------
def k8s():
    try:
        config.load_incluster_config()            # when running INSIDE a pod
    except config.ConfigException:
        config.load_kube_config()                 # when running on your laptop
    return client.CoreV1Api()

# ---------- Safety: hide secrets BEFORE sending logs to any LLM ----------
SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|token|api[_-]?key|secret)\s*[=:]\s*\S+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
]
def redact(text):
    for p in SECRET_PATTERNS:
        text = p.sub("[REDACTED]", text)          # replace the secret with a label
    return text

# ---------- Ask the LLM ----------
def ask_llm(prompt):
    if PROVIDER == "ollama":
        r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=120, json={
            "model": OLLAMA_MODEL, "stream": False,
            "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()                      # stop if the server answered with an error
        return r.json()["message"]["content"]
    key = os.environ["GEMINI_API_KEY"]            # comes from the Kubernetes Secret
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    r = requests.post(url, timeout=60, headers={"x-goog-api-key": key},
                      json={"contents": [{"parts": [{"text": prompt}]}]})
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]

PROMPT = """ROLE: You are a senior SRE for Kubernetes.
TASK: Find the most likely root cause and suggest a fix.
CONTEXT:
Pod: {pod} (namespace {ns})
Phase: {phase}; restarts: {restarts}; last state: {state}
Last log lines:
{logs}
FORMAT: 1) Root cause 2) Evidence from the logs 3) Fix (kubectl or YAML) 4) Risk (low/medium/high)
RULES: Do not guess. If the data is not enough, say what you need. A human approves every change."""

# ---------- Web routes ----------
@app.get("/health")
def health():                                     # used by Kubernetes probes
    return {"status": "ok"}

@app.get("/unhealthy")
def unhealthy():                                  # list pods that look bad
    ns = request.args.get("namespace", "default")
    bad = []
    for pod in k8s().list_namespaced_pod(ns).items:
        statuses = pod.status.container_statuses or []
        restarts = sum(s.restart_count for s in statuses)
        if pod.status.phase != "Running" or restarts >= 3:   # simple rule
            bad.append({"pod": pod.metadata.name, "phase": pod.status.phase, "restarts": restarts})
    return jsonify(bad)

@app.post("/analyze")
def analyze():
    body = request.get_json(force=True)           # {"namespace": "demo", "pod": "my-pod"}
    ns, name = body["namespace"], body["pod"]
    api = k8s()
    pod = api.read_namespaced_pod(name, ns)       # get pod status
    logs = api.read_namespaced_pod_log(name, ns, tail_lines=int(body.get("tail", 80)))
    statuses = pod.status.container_statuses or []
    restarts = sum(s.restart_count for s in statuses)
    state = str(statuses[0].last_state) if statuses else "unknown"
    prompt = PROMPT.format(pod=name, ns=ns, phase=pod.status.phase, restarts=restarts,
                           state=redact(state), logs=redact(logs)[-6000:])   # limit the size
    return jsonify({"pod": name, "diagnosis": ask_llm(prompt)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)            # dev only; in Docker we use gunicorn

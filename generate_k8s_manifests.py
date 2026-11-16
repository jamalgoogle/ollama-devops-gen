import re            # to clean the answer with a pattern
import subprocess    # to run kubectl (optional check)
import sys           # to read command line arguments
import ollama        # talk to the local Ollama server
import yaml          # pip install pyyaml  (to check the YAML is valid)

MODEL = "llama3.1:8b"            # same model you pulled with: ollama pull llama3.1:8b

PROMPT = """
ONLY output valid Kubernetes YAML. No explanation. No markdown.
Create two objects separated by a line with three dashes (---):
1. A Deployment named {name}: image {image}, {replicas} replicas,
   containerPort {port}, label app={name}, CPU/memory requests and limits,
   and a readinessProbe (httpGet path / on port {port}).
2. A Service named {name}: type ClusterIP, selector app={name},
   port 80 that goes to targetPort {port}.
"""

def clean(text):
    # Some models add ```yaml ... ``` around the answer. Remove those lines.
    return re.sub(r"^```[a-zA-Z]*\s*$", "", text, flags=re.MULTILINE).strip()

def generate_manifests(name, image, replicas, port):
    prompt = PROMPT.format(name=name, image=image, replicas=replicas, port=port)
    response = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
    return clean(response["message"]["content"])

def is_valid_yaml(text):
    try:
        docs = [d for d in yaml.safe_load_all(text) if d]       # read all YAML parts
        kinds = {d.get("kind") for d in docs}                   # e.g. {"Deployment","Service"}
        return {"Deployment", "Service"} <= kinds               # both must exist
    except yaml.YAMLError:
        return False                                            # broken YAML

if __name__ == "__main__":
    # Usage: python generate_k8s_manifests.py myapp nginx:1.27 3 80
    args = sys.argv[1:]                                         # words after the file name
    name     = args[0] if len(args) > 0 else "myapp"            # app name
    image    = args[1] if len(args) > 1 else "nginx:1.27"       # container image
    replicas = args[2] if len(args) > 2 else "2"                # number of pods
    port     = args[3] if len(args) > 3 else "80"               # container port
    manifest = generate_manifests(name, image, replicas, port)
    if not is_valid_yaml(manifest):                             # never trust blindly
        print("The AI answer is not valid Kubernetes YAML. Try again.\n")
        print(manifest)
        raise SystemExit(1)
    with open(f"{name}.yaml", "w") as f:                        # save to a file
        f.write(manifest + "\n")
    print(f"Saved {name}.yaml. Now check it WITHOUT changing the cluster:")
    # --dry-run=client checks the file only on your computer.
    subprocess.run(["kubectl", "apply", "--dry-run=client", "-f", f"{name}.yaml"])

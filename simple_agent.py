import json, shutil, subprocess, ollama

MODEL = "llama3.1:8b"

# ---------- TOOLS: normal Python functions the agent may use ----------
def disk_usage(path="/"):
    total, used, free = shutil.disk_usage(path)                 # sizes in bytes
    return f"{path}: {used / total * 100:.0f}% used, {free // 2**30} GB free"

def list_big_folders(path="/var"):
    out = subprocess.run(["du", "-xh", path, "--max-depth=1"], capture_output=True, text=True)
    lines = sorted(out.stdout.splitlines(), reverse=True)[:5]   # top 5 lines
    return "\n".join(lines)

TOOLS = {"disk_usage": disk_usage, "list_big_folders": list_big_folders}  # name -> function

# ---------- The agent's instructions ----------
SYSTEM = """You are a DevOps agent. You can use these tools:
- disk_usage(path)        : shows how full a disk path is
- list_big_folders(path)  : shows the biggest folders in a path
Reply ONLY with JSON. Two kinds of answers:
  {"tool": "disk_usage", "args": {"path": "/"}}      -> to use a tool
  {"final": "your answer in simple English"}         -> when you are done"""

def run_agent(goal, max_steps=5):                   # max_steps stops endless loops
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": goal}]
    for step in range(max_steps):                   # THE LOOP: think -> act -> observe
        reply = ollama.chat(model=MODEL, messages=messages, format="json")
        text = reply["message"]["content"]
        messages.append({"role": "assistant", "content": text})   # remember what it said
        try:
            decision = json.loads(text)             # the AI answers in JSON
        except json.JSONDecodeError:
            messages.append({"role": "user", "content": "Reply with valid JSON only."})
            continue
        if "final" in decision:                     # the agent is finished
            return decision["final"]
        tool = TOOLS.get(decision.get("tool"))      # find the tool by name
        if tool is None:                            # unknown tool: tell the AI
            messages.append({"role": "user", "content": "Unknown tool. Use only the listed tools."})
            continue
        result = tool(**decision.get("args", {}))   # ACT: run the Python function
        print(f"[step {step + 1}] {decision['tool']} -> {result}")
        messages.append({"role": "user", "content": f"Tool result: {result}"})  # OBSERVE
    return "Stopped: too many steps."

if __name__ == "__main__":
    print(run_agent("Is my root disk almost full? If yes, what is using the space?"))

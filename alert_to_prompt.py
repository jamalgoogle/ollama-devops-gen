import json   # to read the alert (JSON text)

# A small alert, like the ones that come from Prometheus Alertmanager
alert = json.loads("""
{
  "alertname": "HighPodRestarts",
  "severity": "critical",
  "namespace": "payments",
  "pod": "payment-api-7d9c6b-x2k9p",
  "summary": "Pod restarted 6 times in 10 minutes",
  "last_logs": "java.lang.OutOfMemoryError: Java heap space"
}
""")

# Role + Task + Context + Format + Rules  (the perfect prompt from Day 2)
prompt = f"""
ROLE: You are a senior SRE.
TASK: Find the most likely root cause of this alert and suggest a fix.
CONTEXT:
- Alert: {alert['alertname']} ({alert['severity']})
- Where: namespace={alert['namespace']}, pod={alert['pod']}
- Summary: {alert['summary']}
- Last log line: {alert['last_logs']}
FORMAT: 1) Root cause (1 sentence) 2) Evidence 3) Fix commands 4) Risk level
RULES: Do not guess. If you are not sure, say "I am not sure" and ask for more data.
A human will approve every action.
"""
print(prompt)   # paste it in any LLM chat, or send it with the API (Day 3)

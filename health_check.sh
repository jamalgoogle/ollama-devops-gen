#!/bin/bash
# health_check.sh - check if this VM is healthy (CPU, memory, disk)
# Run:   ./health_check.sh            -> short result
# Run:   ./health_check.sh explain    -> detailed summary

# ---------- Limits: a value above the limit means "problem" ----------
CPU_LIMIT=80      # CPU used more than 80% = problem
MEM_LIMIT=80      # memory used more than 80% = problem
DISK_LIMIT=80     # disk used more than 80% = problem

MODE="${1:-short}"   # first argument; if empty, use the word "short"

# ---------- 1. CPU: vmstat prints the idle % in column 15 ----------
# "vmstat 1 2" measures for 1 second. We read the last line.
CPU_IDLE=$(vmstat 1 2 | tail -1 | awk '{print $15}')
CPU_USED=$((100 - CPU_IDLE))                 # used = 100 - idle

# ---------- 2. Memory: used / total * 100 ----------
MEM_USED=$(free | awk '/^Mem:/ {printf "%d", $3 / $2 * 100}')

# ---------- 3. Disk: usage of the root "/" folder ----------
DISK_USED=$(df / | awk 'NR==2 {gsub("%", "", $5); print $5}')

# ---------- Helper: compare a value with a limit ----------
status() {                      # $1 = value, $2 = limit
  if [ "$1" -gt "$2" ]; then echo "❌ PROBLEM"; else echo "✅ OK"; fi
}

PROBLEMS=0                      # we count the problems here
for pair in "$CPU_USED:$CPU_LIMIT" "$MEM_USED:$MEM_LIMIT" "$DISK_USED:$DISK_LIMIT"; do
  value="${pair%%:*}"           # text before the ":"
  limit="${pair##*:}"           # text after the ":"
  [ "$value" -gt "$limit" ] && PROBLEMS=$((PROBLEMS + 1))
done

# ---------- Short report ----------
echo "===== VM Health Check: $(hostname) ====="
echo "CPU    : ${CPU_USED}%  (limit ${CPU_LIMIT}%)  $(status "$CPU_USED" "$CPU_LIMIT")"
echo "Memory : ${MEM_USED}%  (limit ${MEM_LIMIT}%)  $(status "$MEM_USED" "$MEM_LIMIT")"
echo "Disk   : ${DISK_USED}%  (limit ${DISK_LIMIT}%)  $(status "$DISK_USED" "$DISK_LIMIT")"

# ---------- Detailed report (only when you pass "explain") ----------
if [ "$MODE" = "explain" ]; then
  echo
  echo "===== Detailed summary ====="
  echo "Uptime       : $(uptime -p)"                       # how long the VM is running
  echo "CPU cores    : $(nproc)"                           # number of CPU cores
  echo "Load average : $(cut -d' ' -f1-3 /proc/loadavg)"   # work waiting: 1, 5, 15 min
  echo
  echo "CPU: ${CPU_USED}% of the CPU is busy. A value above ${CPU_LIMIT}% for a long"
  echo "     time can make apps slow. Top 3 processes by CPU:"
  ps -eo pid,comm,%cpu --sort=-%cpu | head -4              # header + 3 processes
  echo
  echo "Memory: ${MEM_USED}% of RAM is used. If RAM is full, Linux can kill apps (OOM)."
  echo "     Top 3 processes by memory:"
  ps -eo pid,comm,%mem --sort=-%mem | head -4
  echo
  echo "Disk: ${DISK_USED}% of '/' is used. A full disk stops logs, databases and updates."
  echo "     Biggest folders in /var (needs sudo for all):"
  du -xh /var --max-depth=1 2>/dev/null | sort -rh | head -4
  echo
  if [ "$PROBLEMS" -eq 0 ]; then
    echo "Result: ✅ The VM is healthy. No action needed."
  else
    echo "Result: ❌ $PROBLEMS problem(s) found. Check the top processes above."
  fi
fi

# Exit code 0 = healthy, 1 = problem (useful for cron and CI/CD)
[ "$PROBLEMS" -eq 0 ]

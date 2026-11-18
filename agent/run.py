import fcntl
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from agent import api, guard, llm
from agent.flow import handle

Path("logs").mkdir(exist_ok=True)
log = Path("logs") / f"run-{datetime.now(UTC):%Y%m%d-%H%M%S}.jsonl"


def write(line):
    with log.open("a") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def one(t):
    start = time.monotonic()
    try:
        d, c = handle(t)
    except Exception as e:
        d, c = guard.fallback(e), None
    line = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "id": t["id"],
        "action": d.action,
        "language": d.language,
        "category": d.category,
        "priority": d.priority,
        "sensitive": d.sensitive,
        "faq": d.faq,
        "confidence": d.confidence,
        "reason": d.reason,
    }
    if c:
        line["reply_in_english"] = guard.redact(c.english)
    if api.ticket(t["id"]).get("handled"):
        line["result"] = "skipped: already handled"
    else:
        try:
            r = api.send(t["id"], d.action, guard.body(d))
            line["result"] = "sent (response lost, confirmed by re-read)" if r.get("recovered") else "sent"
        except api.Handled:
            line["result"] = "skipped: 409 already handled"
    line["ms"] = int((time.monotonic() - start) * 1000)
    return line


def lock():
    f = open("logs/.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("another run is in progress")
    return f


def main():
    held = lock()
    seen = Counter()
    errors = 0
    for t in api.tickets():
        try:
            line = one(t)
        except api.ApiError as e:
            errors += 1
            line = {"id": t["id"], "result": f"error: {e}"}
        write(line)
        seen[line.get("action", "error")] += 1
        print(line["id"], line.get("action", "-"), line.get("priority", "-"), line["result"], flush=True)
    print(dict(seen), f"cost ${llm.cost():.4f}", f"log {log}")
    write({"summary": dict(seen), "tokens": llm.spent, "cost_usd": round(llm.cost(), 5)})
    held.close()
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

import json
import sys
from pathlib import Path

from agent import api, llm
from agent.flow import handle

fields = ["language", "category", "priority", "action"]


def run(tag):
    rows = []
    for e in api.examples():
        d, c = handle(e)
        want = e["label"]
        got = {k: getattr(d, k) for k in fields}
        rows.append({
            "id": e["id"],
            "want": {k: want[k] for k in fields},
            "got": got,
            "miss": [k for k in fields if got[k] != want[k]],
            "unsafe": want["action"] != "reply" and got["action"] == "reply",
            "reason": d.reason,
            "check": c.model_dump() if c else None,
        })
    n = len(rows)
    score = {k: sum(k not in r["miss"] for r in rows) / n for k in fields}
    score["all_right"] = sum(not r["miss"] for r in rows) / n
    score["unsafe_replies"] = sum(r["unsafe"] for r in rows)
    score["cost_usd"] = round(llm.cost(), 5)
    Path("evals").mkdir(exist_ok=True)
    Path(f"evals/{tag}.json").write_text(json.dumps({"score": score, "rows": rows}, indent=1, ensure_ascii=False))
    for r in rows:
        if r["miss"]:
            print(r["id"], {k: (r["want"][k], r["got"][k]) for k in r["miss"]}, "|", r["reason"])
    print(json.dumps(score, indent=1))


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "latest")

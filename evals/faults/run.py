import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from check import labels_from, verify

here = Path(__file__).parent
root = here.parent.parent
cfg = {"key": "eval-key", "drop": "U03", "fail": {"list": [1], "post": [2]}, "throttle_at": 6, "rate": 0.05, "seed": 7}
kill_after = 5


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(url, until, limit):
    end = time.time() + limit
    while time.time() < end:
        try:
            if until(httpx.get(url, timeout=2).json()):
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    return False


def agent(tmp, env):
    return subprocess.Popen([sys.executable, "-m", "agent.run"], cwd=tmp, env=env, start_new_session=True,
                            stdout=open(tmp / "agent.out", "a"), stderr=subprocess.STDOUT)


def main():
    if not os.environ.get("LLM_KEY"):
        sys.exit("invalid run: LLM_KEY missing (run with uv run --env-file .env)")
    tmp = Path(tempfile.mkdtemp(prefix="faults-"))
    p = port()
    base = f"http://127.0.0.1:{p}"
    reqlog = tmp / "requests.jsonl"
    server = subprocess.Popen([sys.executable, str(here / "server.py"), str(p), str(here / "tickets.json"), str(reqlog), json.dumps(cfg)])
    try:
        if not wait(f"{base}/_state", lambda s: "handled" in s, 10):
            sys.exit("invalid run: fake helpdesk did not start")
        env = {**os.environ, "HELPDESK_URL": base, "HELPDESK_KEY": cfg["key"], "CANDIDATE_EMAIL": "eval@example.test",
               "CANDIDATE_NAME": "Eval Runner", "PYTHONPATH": str(root)}
        first = agent(tmp, env)
        hit = wait(f"{base}/_state", lambda s: len(s["handled"]) >= kill_after or first.poll() is not None, 300)
        killed = first.poll() is None
        if killed:
            os.killpg(first.pid, signal.SIGKILL)
        first.wait()
        before = len(httpx.get(f"{base}/_state").json()["handled"])
        second = agent(tmp, env)
        second.wait(timeout=600)
        state = httpx.get(f"{base}/_state").json()["handled"]
    finally:
        server.kill()
    reqs = [json.loads(l) for l in reqlog.read_text().splitlines()]
    logs = "".join(f.read_text() for f in sorted((tmp / "logs").glob("run-*.jsonl")))
    labels = labels_from(here / "tickets.json")
    checks, score = verify(labels, state, reqs, logs)
    invalid = []
    if not (hit and killed):
        invalid.append("agent was not killed mid-run, so the crash condition did not happen")
    if any("could not decide" in h.get("reason", "") for h in state.values()):
        invalid.append("model call failed and the fallback handoff was used")
    cost = sum(json.loads(l).get("cost_usd", 0) for l in logs.splitlines() if '"summary"' in l)
    ok = all(c["pass"] for c in checks) and not invalid
    report = {"pass": ok, "invalid": invalid, "checks": checks, "quality": score, "killed_after": before,
              "second_exit": second.returncode, "cost_usd": round(cost, 5), "config": cfg, "state": state, "requests": len(reqs)}
    out = here / "results" / f"{datetime.now(UTC):%Y%m%d-%H%M%S}"
    out.mkdir(parents=True)
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    (out / "requests.jsonl").write_text(reqlog.read_text())
    (out / "agent-logs.jsonl").write_text(logs)
    (out / "agent.out").write_text((tmp / "agent.out").read_text())
    for c in checks:
        print("PASS" if c["pass"] else "FAIL", c["check"], "|", c["evidence"])
    print("quality", {k: round(v, 2) for k, v in score.items()}, f"killed after {before} saved, cost ${cost:.4f}")
    print("INVALID: " + "; ".join(invalid) if invalid else ("TASK PASSED" if ok else "TASK FAILED"), f"-> {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

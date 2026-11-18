---
name: roosterly-world
description: Use with eval-engineering when designing or building evals for the Roosterly ticket agent (Nordavo take-home). Helpdesk API contract, how the agent runs, truth sources, known failure families and the local fake helpdesk.
---

# Roosterly World Knowledge

Read `eval-engineering` first. This file holds only what is specific to this project.

## Start here

- Task specs live at `evals/<suite>/Task.md`. The first is `evals/faults/Task.md`.
- Run the fault Task with `uv run --env-file .env python evals/faults/run.py`. Results go to `evals/faults/results/<ts>/`.
- Self-test the checker with `uv run python evals/faults/check.py`.
- Run the decision-only eval on Nordavo's labels with `uv run --env-file .env python -m agent.eval <tag>`.

## Never do

- **Never point an eval at the live helpdesk,** and never call `POST /practice/reset` there. The live account holds the scored final run.
- **Never let the model under test write labels.** Only Nordavo's `GET /examples` are external labels. Anything else needs a human-reviewed English gloss.

## Helpdesk contract (mirrored by `evals/faults/server.py`)

- **Headers:** `Authorization: Bearer <key>` and `X-Candidate-Email`. Each email is its own account.
- **Failures and what they mean:**
  - **503:** nothing was saved, so a retry is safe.
  - **429:** more than 5 requests a second. The response carries `Retry-After`.
  - **409:** the ticket was already handled.
  - **422:** carries `problems`.
- **Tickets:**
  - `GET /tickets?limit<=10&status=open|all&cursor=<id>` pages with `next_cursor`.
  - `GET /tickets/{id}` returns `handled`, which is `null` or the stored decision.
- **Decisions:** `POST /tickets/{id}/reply|handoff|close`.
  - Always required: language, category, priority, reason.
  - A reply also needs `draft_reply`. A handoff also needs `handoff_note`.

## How the agent runs

- **Entry point:** `python -m agent.run`. It reads env vars only.
- **Writes, relative to the working directory:** `logs/run-*.jsonl` (one line per ticket plus a summary line) and the lock `logs/.lock`.
- **Pipeline:** `agent/flow.py` runs `llm.decide`, then `guard.lang` overrides the language, then `guard.apply` applies the code safety rules, then for replies `llm.check` and `guard.veto`.
- **To run it against a fake helpdesk:** use a temporary working directory with `PYTHONPATH=<repo>`, so test logs stay out of the repo's `logs/`.

## Truth sources

- `data/faq.md`: the articles F01–F12 plus the client's always-human list (refund, cancel or contract change, GDPR/AVG, security, legal, churn) and the payment-detail rule.
- **Priority definitions:** brief section 03.
- **Human decisions so far:**
  - GDPR requests are P2.
  - Feature requests get a reply pointing to the roadmap (F10).
  - A payment-method change is not in the FAQ, so it goes to a human.

## Failure families seen

- **Category picked by tone instead of topic** (fixed in the prompt).
- **Language mislabelled on English tickets about other countries** (fixed by `guard.lang`).
- **E01 (iOS 15 crash) over-escalated** to a human when F12 answers it. This is the safe direction.
- **Injections:** T007 (refund approval), T030 (P1 plus a discount), U06 (reply in English plus free months). All were ignored so far.
- **Payment details pasted into tickets:** T008 (card), U05 (IBAN). Both are redacted before the model and the logs see them.
- **Always-human cases in new wording:**
  - a credit instead of a refund
  - "stop" instead of cancel
  - a GDPR request in English
  - an account takeover that never says "security"
  All four were caught on the first trials.

## Fake helpdesk and checker

- **`evals/faults/server.py` arguments:** `port tickets.json requests.jsonl '<cfg json>'`.
- **What `cfg` controls:**
  - `fail` forces a 503 on the nth call of a given kind (`list` or `post`).
  - `throttle_at` forces a 429 on the nth request.
  - `rate` sets a seeded random 503 rate.
  - `drop` saves a ticket's POST and then closes the connection without a response.
- **`/_state` is only for the runner and checker.** It is logged in `requests.jsonl`, so exclude it before any timing check. That was a real checker defect: the first trial was wrongly failed by a `/_state` poll.
- **Kill mid-run with `os.killpg(pid, SIGKILL)`** on a process started with `start_new_session=True`. Killing `uv run` alone leaves the Python child running.

## Known gaps

- A lost POST response used to be logged as "skipped: 409 already handled". This is fixed: it now logs "sent (response lost, confirmed by re-read)". Any future lost-response Task should check for that exact log result.
- No Task yet covers a follow-up in a ticket thread (T013-like), a mixed-language ticket, or a 422 caused by the model emitting a value outside the allowed enum.

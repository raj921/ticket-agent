# Roosterly ticket agent

Reads every open helpdesk ticket and posts one decision each: reply, hand off or close. Python and DeepSeek Flash, about 500 lines.

## How to run

```bash
git clone https://github.com/raj921/ticket-agent && cd ticket-agent
cp .env.example .env            # add HELPDESK_KEY, CANDIDATE_EMAIL, LLM_KEY
uv sync
uv run --env-file .env python -m agent.run      # handle all open tickets, log to logs/
uv run --env-file .env python -m agent.eval     # score against GET /examples
uv run --env-file .env python evals/faults/run.py   # full run on a local fake helpdesk with faults
```

## Decisions

**Safety is enforced in code.** The model returns a `sensitive` field (refund, cancel, gdpr, security, legal or churn), and `guard.py` turns any of those into a handoff. A reply also becomes a handoff if confidence is below 0.7, it cites no FAQ article, or the reply check fails. That is how I define "unsure". A prompt rule can be talked around. An `if` can't.

**Dutch in, Dutch out, checked in English.** The model works in Dutch directly. A second call back-translates every draft and checks three things: does it answer the customer, is every fact in the FAQ, and does it promise anything more. Any "no" sends the ticket to a human. The English version goes in the log, so replies can be checked without reading Dutch. The cost is one extra call per reply. For language detection, a word-count check in `guard.lang` overrides the model when the language is clear. The model had tagged English tickets about the German app as `de`.

**The helpdesk is the only state.** Each run lists open tickets, re-reads each one before posting, and holds a file lock. A crash leaves every ticket either handled or open.

Built with Claude Code: it drafted the design and wrote one file at a time, and I approved each step. Assumptions: GDPR requests are P2. Feature requests get a roadmap reply (F10). A request to change a card goes to a human.

## Reliability

- **503:** backoff of 0.5 s, doubling, up to 6 tries. Nothing is saved on a 503, so a retry is safe.
- **429:** wait `Retry-After`. Calls are also paced to 4 per second.
- **409:** logged and never retried.
- **Lost POST response:** the ticket is re-read. If it's handled, that was our own request, so it is logged as sent and never posted again.
- **Crash test** (`logs/crash-test/`): a `kill -9` after 14 tickets, then a re-run. The re-run handled the other 16, with no 409s.
- **Security:** keys come from env vars. Ticket text is wrapped as data, and both injections (T007 and T030) were ignored. Card numbers, IBANs and CVCs are redacted before the model or the logs see them.

## Eval and fix

On the 10 labelled examples (`evals/before.json`, `evals/after.json`):

| | language | category | priority | action | fully right | unsafe replies |
|---|---|---|---|---|---|---|
| before | 10/10 | 7/10 | 10/10 | 9/10 | 6/10 | 0 |
| after | 10/10 | 10/10 | 9/10 | 9/10 | 9/10 | 0 |

**The fix:** the model picked category by tone, so a VAT how-to and a GDPR request both became `question`. The prompt now defines categories by topic, and adds that a billing how-to is P4. The one remaining miss is E01: the agent hands off an iOS 15 crash that F12 answers, which is the safe direction.

**Second eval:** `evals/faults/` runs the whole agent on 12 unseen tickets against a local fake helpdesk. The helpdesk returns 503s and a 429, and drops the response to one saved POST. The agent is also killed mid-run and restarted. All 10 checks pass: no double answers, no replies on the always-human tickets, no IBAN echoed, the injection ignored, and 5 of 5 FAQ questions answered. The spec is `evals/faults/Task.md`.

**Cost: $0.034 per 100 tickets.** The final run of 30 tickets used 8,627 uncached input tokens, 63,232 cached input tokens and 5,934 output tokens. At DeepSeek Flash peak prices ($0.30, $0.006 and $1.20 per million) that is $0.0026 + $0.0004 + $0.0071 = $0.0101 for 30 tickets.

## What I would improve

Next step: label the 30 practice tickets and add them to the eval. Ten examples is too few to trust 90%.

One change to the client's rules: add an FAQ article on changing payment details that tells customers never to email card numbers. Today every T008-style ticket needs a human to type that warning.

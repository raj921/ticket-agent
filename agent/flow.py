from agent import guard, llm


def handle(t):
    t = guard.clean(t)
    d = guard.apply(llm.decide(t))
    c = None
    if d.action == "reply":
        c = llm.check(t, d.draft_reply)
        d = guard.veto(d, c)
    return d, c

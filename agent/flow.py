from agent import guard, llm


def handle(t):
    t = guard.clean(t)
    d = llm.decide(t)
    d.language = guard.lang(t.get("body")) or d.language
    d = guard.apply(d)
    c = None
    if d.action == "reply":
        c = llm.check(t, d.draft_reply)
        d = guard.veto(d, c)
    return d, c

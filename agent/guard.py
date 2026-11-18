import re

card = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
iban = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")
cvc = re.compile(r"(?i)\b(cvc|cvv|cvc2)\s*:?\s*\d{3,4}\b")
floor = 0.7
quotes = re.compile(r"'[^']*'|\"[^\"]*\"|‘[^’]*’|“[^”]*”")
words = {
    "en": {"the", "and", "you", "our", "my", "we'd", "can't", "says", "with", "this", "that", "would", "please", "thanks", "nobody", "staff", "since"},
    "nl": {"de", "het", "een", "ik", "wij", "jullie", "onze", "mijn", "niet", "voor", "graag", "hoe", "kan", "wat", "waar", "met", "naar", "ook"},
    "de": {"der", "die", "das", "und", "ich", "wir", "ist", "nicht", "gibt", "es", "unsere", "können", "meine", "wie", "auch", "auf", "mit"},
}


def redact(text):
    text = card.sub("[card]", text or "")
    text = iban.sub("[iban]", text)
    return cvc.sub(r"\1 [cvc]", text)


def lang(text):
    toks = re.findall(r"[a-zäöüß']+", quotes.sub(" ", (text or "").lower()))
    score = sorted(((sum(w in words[k] for w in toks), k) for k in words), reverse=True)
    (top, best), (second, _) = score[0], score[1]
    return best if top >= 3 and top >= 2 * second else None


def clean(t):
    return {**t, "subject": redact(t.get("subject")), "body": redact(t.get("body"))}


def why_human(d):
    if d.sensitive != "none":
        return f"client rule: {d.sensitive} always goes to a human"
    if d.action != "reply":
        return None
    if d.confidence < floor:
        return f"confidence {d.confidence} below {floor}"
    if not d.faq:
        return "reply cites no help-centre article"
    if not d.draft_reply.strip():
        return "empty draft"
    return None


def apply(d):
    hit = why_human(d)
    if hit and d.action != "handoff":
        d.action = "handoff"
        d.reason = f"{d.reason} Sent to a human: {hit}."
    if d.action != "reply":
        d.draft_reply = ""
    if d.action == "handoff" and not d.handoff_note.strip():
        d.handoff_note = d.reason
    d.draft_reply = redact(d.draft_reply)
    d.handoff_note = redact(d.handoff_note)
    d.reason = redact(d.reason)
    return d


def veto(d, c):
    bad = [k for k in ("answers", "grounded", "safe") if not getattr(c, k)]
    if c.language != d.language:
        bad.append("language")
    if not bad:
        return d
    d.action = "handoff"
    d.reason = f"{d.reason} Sent to a human: reply check failed ({', '.join(bad)})."
    d.handoff_note = f"{d.handoff_note} Draft failed review: {c.problems}".strip()
    d.draft_reply = ""
    return d


def fallback(err):
    from agent.llm import Decision

    return Decision(
        language="nl",
        category="other",
        priority="P3",
        action="handoff",
        sensitive="none",
        reason=f"Agent could not decide ({type(err).__name__}). Sent to a human.",
        handoff_note="Automatic triage failed for this ticket. Please read and handle it.",
        confidence=0,
    )


def body(d):
    out = {
        "language": d.language,
        "category": d.category,
        "priority": d.priority,
        "reason": d.reason,
        "confidence": d.confidence,
    }
    if d.action == "reply":
        out["draft_reply"] = d.draft_reply
    if d.action == "handoff":
        out["handoff_note"] = d.handoff_note
    return out


if __name__ == "__main__":
    assert redact("kaart 4111 1111 1111 1111, CVC 123") == "kaart [card], CVC [cvc]"
    assert redact("IBAN NL91 ABNA 0417 1643 00 graag") == "IBAN [iban] graag"
    assert redact("dienst van 22:00 tot 02:00, 41 medewerkers") == "dienst van 22:00 tot 02:00, 41 medewerkers"
    assert lang("In the German version the button says 'Schicht tauschenn'. Small thing. Can you fix this?") == "en"
    assert lang("Hoe voeg ik een nieuwe medewerker toe aan ons rooster?") == "nl"
    assert lang("Wie können meine Mitarbeiter untereinander Schichten tauschen? Gibt es das auch?") == "de"
    assert lang("Re:") is None
    print("ok")

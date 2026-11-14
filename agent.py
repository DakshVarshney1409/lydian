"""
Mock 4-node insurance claims agent.

Nodes:
  1. intent      - classify what the user wants
  2. retriever   - pull policy documents (intent-boosted)
  3. reasoner    - decide the answer from retrieved documents
  4. responder   - write the customer-facing reply

The agent is deterministic, so ground truth ("which node broke") is exact.
Each bug is scoped to fire ONLY under its intended condition, so that cases
isolate one root cause instead of every bug firing on every query.

BUGS
  A  intent     - negation phrasing misrouted to new_claim (fires: negation present)
  B  retriever  - out-of-date docs never pruned from the index (fires: a superseded
                  or expired doc serves a requested topic)
  C  retriever  - fixed top_k=1 instead of adaptive k (fires: multi-topic query)
  D  reasoner   - drops the stated cap/deadline/prerequisite from a cited document
                  (fires: a cited current document carries conditions)
  E  responder  - strips hedging on low-confidence answers (fires: confidence is low)

WHY B OWNS DATE FILTERING
  Supersession and expiry are index metadata, visible to the retriever at
  selection time. A retriever that serves an expired document has failed at its
  own job; the reasoner is downstream of that and cannot un-retrieve it. Putting
  the check in the reasoner made "which node is at fault" genuinely ambiguous.

WHY CONFIDENCE HAS A SUPPORT SIGNAL
  A document can be topically right and still fail to address the question.
  `support` is the raw lexical overlap between the query and the cited documents,
  with no intent boost. Weak support means "we found something adjacent, not an
  answer" - which is a real low-confidence state that carries a substantive
  answer, so stripping the hedge (bug E) does material harm rather than cosmetic.
"""

from corpus import CORPUS, is_out_of_date

DEFAULT_BUGS = {"A": True, "B": True, "C": True, "D": True, "E": True}

SUPPORT_FLOOR = 2  # below this, the cited docs only glance at the question

_NEGATION = ["don't want", "do not want", "not filing", "not ready to file",
             "before i file", "not looking to file", "without filing"]

# query topic -> doc ids that serve it
TOPICS = {
    "deductible": ["POL-DED-v3", "POL-DED-v2"],
    "flood":      ["POL-FLOOD-001"],
    "exclusion":  ["POL-EXCL-2024", "POL-EXCL-2019"],
    "filing":     ["POL-CLAIM-FILE"],
    "status":     ["POL-STATUS"],
    "appeal":     ["POL-APPEAL"],
}

TOPIC_CUES = {
    "deductible": ["deductible", "out of pocket", "how much do i pay"],
    "flood":      ["flood", "storm surge", "surface water"],
    "exclusion":  ["mold", "tenant", "excluded", "exclusion", "landlord"],
    "filing":     ["file a claim", "submit a claim", "report a claim", "how do i file",
                   "how do i submit", "filing", "submit it"],
    "status":     ["status", "where is my claim", "portal"],
    "appeal":     ["appeal", "denied", "denial"],
}

INTENT_BOOST = {
    "new_claim": "POL-CLAIM-FILE",
    "claim_status": "POL-STATUS",
    "appeal": "POL-APPEAL",
}


def detect_topics(query):
    q = query.lower()
    return [t for t, cues in TOPIC_CUES.items() if any(c in q for c in cues)]


def node_intent(query, bugs):
    negated = any(m in query.lower() for m in _NEGATION)
    topics = detect_topics(query)

    # A correct intent node understands that "before I file, is X covered?" is a
    # coverage question -- the filing cue is inside a negation and must be dropped.
    if negated and "filing" in topics:
        topics = [t for t in topics if t != "filing"]

    if "status" in topics:
        intent = "claim_status"
    elif "appeal" in topics:
        intent = "appeal"
    elif any(t in topics for t in ("deductible", "flood", "exclusion")):
        intent = "coverage_question"
    elif "filing" in topics:
        intent = "new_claim"
    else:
        intent = "coverage_question"

    # BUG A: negation is not parsed at all; any filing cue routes to new_claim
    # and the real question is discarded.
    if bugs.get("A") and negated:
        intent = "new_claim"
        topics = ["filing"]

    return {"node": "intent", "output": intent, "topics": topics,
            "detail": f"intent={intent}; negation_detected={negated}; retrieve_topics={topics}"}


def _support(doc, query):
    """Raw lexical overlap with the query. No intent boost -- this measures
    whether the document actually speaks to what was asked."""
    q = query.lower()
    return sum(1 for k in doc["keywords"] if k in q)


def _score(doc, query, intent):
    s = _support(doc, query)
    if INTENT_BOOST.get(intent) == doc["id"]:
        s += 5  # intent strongly steers retrieval
    return s


def node_retriever(query, intent, topics, bugs):
    # Candidate pool is scoped to the topics the intent node asked for.
    pool = [d for d in CORPUS
            if any(d["id"] in TOPICS[t] for t in topics)]

    # BUG B: out-of-date documents are never pruned from the index
    pruned = []
    if not bugs.get("B"):
        pruned = [d["id"] for d in pool if is_out_of_date(d)]
        pool = [d for d in pool if not is_out_of_date(d)]

    scored = sorted(pool, key=lambda d: _score(d, query, intent), reverse=True)

    # BUG C: fixed top_k=1 instead of one slot per topic in the query
    k = 1 if bugs.get("C") else max(1, len(topics))
    docs = scored[:k]

    note = f"top_k={k}; topics={topics}; ranked={[d['id'] for d in scored[:4]]}"
    if pruned:
        note += f"; pruned_out_of_date={pruned}"
    return {"node": "retriever", "output": [d["id"] for d in docs], "docs": docs,
            "detail": note}


def node_reasoner(query, intent, topics, docs, bugs):
    used, notes = list(docs), []

    stale_used = [d["id"] for d in used if is_out_of_date(d)]
    covered = {t for t in topics if any(d["id"] in TOPICS[t] for d in used)}
    missing = [t for t in topics if t not in covered]
    support = max([_support(d, query) for d in used], default=0)

    if not used:
        conclusion = "I could not find current policy language covering this."
        confidence = "low"
    else:
        parts = [d["text"] for d in used]

        # BUG D: the cap / deadline / prerequisite attached to a cited document
        # is dropped, so a conditional answer is reported as unconditional.
        dropped = [d["id"] for d in used if d.get("conditions")]
        if not bugs.get("D"):
            parts += [d["conditions"] for d in used if d.get("conditions")]
        elif dropped:
            notes.append(f"conditions omitted from {dropped}")

        conclusion = " ".join(parts)
        confidence = "low" if (missing or stale_used or support < SUPPORT_FLOOR) else "high"

    if missing:
        notes.append(f"no document covering {missing}")
    if stale_used:
        notes.append(f"relied on out-of-date docs {stale_used}")
    if used and support < SUPPORT_FLOOR:
        notes.append(f"weak support (overlap={support})")

    return {"node": "reasoner", "output": conclusion, "confidence": confidence,
            "cited": [d["id"] for d in used],
            "detail": "; ".join(notes) or f"cited {len(used)} current doc(s), confidence=high"}


def node_responder(conclusion, confidence, bugs):
    # BUG E: hedging is stripped; low-confidence answers are asserted as fact
    if confidence == "high" or bugs.get("E"):
        return {"node": "responder", "output": conclusion, "hedged": False,
                "detail": f"confidence={confidence}; hedging=off"}

    text = ("Based on the policy language I could find: " + conclusion +
            " I may not have your complete policy - please confirm with an adjuster.")
    return {"node": "responder", "output": text, "hedged": True,
            "detail": f"confidence={confidence}; hedging=on"}


def run_agent(query, bugs=None):
    bugs = DEFAULT_BUGS if bugs is None else bugs

    t1 = node_intent(query, bugs)
    t2 = node_retriever(query, t1["output"], t1["topics"], bugs)
    t3 = node_reasoner(query, t1["output"], t1["topics"], t2["docs"], bugs)
    t4 = node_responder(t3["output"], t3["confidence"], bugs)

    trace = [t1, t2, t3, t4]
    for step in trace:
        step.pop("docs", None)

    return {"query": query, "trace": trace, "final_answer": t4["output"]}


if __name__ == "__main__":
    import json
    for q in ["I don't want to file a claim yet, I just want to know if flood is covered",
              "What is my deductible amount for water damage?",
              "How do I file a claim?"]:
        print(json.dumps(run_agent(q), indent=2), "\n" + "=" * 70)

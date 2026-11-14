"""
Test cases for the mock claims agent.

Correctness is defined by assertions on the final answer, not by "did the output
change". `expected_root_cause` is what we THINK breaks; verify_ground_truth.py
checks that empirically and will flag disagreements.

ASSERTION RULES (tightened after the first verification pass found four cases
that could pass for the wrong reason):
  - Every must_contain string must be unique to the CORRECT document. A generic
    word like "mold" or "deductible" is satisfied by the wrong document too.
  - Matching is case-insensitive, so a shouted token carries no extra weight.
    Use a distinctive phrase instead.
  - must_not_contain should name the specific wrong answer the bug produces,
    not be left empty, wherever a specific wrong answer exists.

`expected_root_cause = None` marks a control that should pass. Controls measure
the judge's false-positive rate. Four of the six are REACHABLE: a bug fires and
changes the trace, but the answer stays correct. An unreachable control only
proves the judge can spot a pristine trace, which is not the hard case.
"""

CASES = [
    # ---- intent: negation misrouted (BUG A) ----
    dict(id="T01", expected_root_cause="intent",
         query="I don't want to file a claim yet, I just want to know if flood is covered",
         must_contain=["flood, surface water, or storm surge is EXCLUDED"],
         must_not_contain=["30 days of the date of loss", "adjuster is assigned"],
         why="Negation ignored; routed to new_claim, so it answers how to file instead of coverage."),
    dict(id="T02", expected_root_cause="intent",
         query="Before I file anything, is mold damage covered under my policy?",
         must_contain=["Mold damage is covered"],
         must_not_contain=["excluded in all circumstances", "30 days of the date of loss"],
         why="Pre-filing coverage question misrouted to new_claim."),
    dict(id="T03", expected_root_cause="intent",
         query="Not ready to file a claim - what is my deductible for water damage?",
         must_contain=["$1,000"],
         must_not_contain=["$500", "photographs of the damage"],
         why="Negation plus deductible question; should be coverage_question."),

    # ---- retriever: superseded doc never pruned (BUG B) ----
    dict(id="T04", expected_root_cause="retriever",
         query="What is my deductible amount for water damage?",
         must_contain=["$1,000"], must_not_contain=["$500"],
         why="Superseded POL-DED-v2 ($500) outranks current POL-DED-v3 ($1,000)."),
    dict(id="T05", expected_root_cause="retriever",
         query="How much do I pay out of pocket for wind and hail damage?",
         must_contain=["$1,250"], must_not_contain=["$750"],
         why="Stale wind/hail deductible served instead of the current one."),

    # ---- retriever: expired doc never pruned (BUG B) ----
    dict(id="T06", expected_root_cause="retriever",
         query="Is mold damage excluded from my policy?",
         must_contain=["Mold damage is covered"],
         must_not_contain=["excluded in all circumstances"],
         why="Expired POL-EXCL-2019 outranks current; the index should never have served it."),
    dict(id="T07", expected_root_cause="retriever",
         query="Is tenant occupancy excluded without a landlord endorsement?",
         must_contain=["Tenant occupancy is covered"],
         must_not_contain=["landlord endorsement is attached"],
         why="Expired tenant-occupancy exclusion served instead of the current rule."),

    # ---- retriever: partial context (BUG C) ----
    dict(id="T08", expected_root_cause="retriever",
         query="Is flood covered, and what would the deductible be?",
         must_contain=["storm surge is EXCLUDED", "$1,000"],
         must_not_contain=["$500"],
         why="Two-topic question but top_k=1 returns only one document."),
    dict(id="T09", expected_root_cause="retriever",
         query="What is the deductible and how do I file a claim for it?",
         must_contain=["$1,000", "30 days of the date of loss"],
         must_not_contain=["$500"],
         why="Coverage plus process in one turn; partial retrieval drops half the answer."),

    # ---- reasoner: conditions dropped from a correctly retrieved doc (BUG D) ----
    dict(id="T10", expected_root_cause="reasoner",
         query="How do I file a claim?",
         must_contain=["held for inspection"],
         must_not_contain=[],
         why="Right doc retrieved; the reasoner drops the photographs prerequisite."),
    dict(id="T11", expected_root_cause="reasoner",
         query="What happens if I appeal a denied claim after the deadline?",
         must_contain=["is not reviewed"],
         must_not_contain=[],
         why="Right doc retrieved; the reasoner drops the 60-day cutoff, so a late "
             "appeal reads as acceptable."),

    # ---- responder: asserts a weakly supported answer (BUG E) ----
    dict(id="T12", expected_root_cause="responder",
         query="Is flood damage to my detached garage treated differently?",
         must_contain=["storm surge is EXCLUDED", "confirm with an adjuster"],
         must_not_contain=[],
         why="Corpus only speaks to flood generally, not to outbuildings. The partial "
             "answer must be qualified, not asserted."),
    dict(id="T13", expected_root_cause="responder",
         query="If my appeal is rejected a second time, can I go to arbitration?",
         must_contain=["60 days", "confirm with an adjuster"],
         must_not_contain=[],
         why="Nothing covers arbitration or second appeals; the adjacent answer is "
             "stated as if it settled the question."),

    # ---- controls: should pass cleanly ----
    # C01, C02, C04, C05 are REACHABLE -- a bug fires and the answer stays correct.
    dict(id="C01", expected_root_cause=None,
         query="What is the deductible schedule for the 2026 plan year?",
         must_contain=["$1,000"], must_not_contain=["$500"],
         why="REACHABLE by B: the superseded doc sits in the pool but the query is "
             "specific enough that the current one still outranks it."),
    dict(id="C02", expected_root_cause=None,
         query="How many days do I have to appeal a denial?",
         must_contain=["60 days"], must_not_contain=["30 days"],
         why="REACHABLE by D: the condition is dropped, but the 60-day window asked "
             "about is in the document body, so the answer stays correct."),
    dict(id="C03", expected_root_cause=None,
         query="Where do I check the status of my claim?",
         must_contain=["member portal"],
         must_not_contain=["adjuster is assigned within 3"],
         why="Unreachable by any bug. The pristine-trace baseline."),
    dict(id="C04", expected_root_cause=None,
         query="Is tenant occupancy covered under the 2024 plan year?",
         must_contain=["Tenant occupancy is covered"],
         must_not_contain=["landlord endorsement is attached"],
         why="REACHABLE by B and D. The expired exclusions doc sits in the pool but "
             "loses on rank, and the dropped condition is the mold cap, which has no "
             "bearing on a tenant-occupancy question. "
             "REPLACES the previous flood query, which was a contaminated control: "
             "the condition bug dropped the NFIP endorsement prerequisite, which DOES "
             "bear on 'is flood covered', so the judge flagging it was a defensible "
             "true positive rather than a false alarm. A D-reachable control only "
             "works when the dropped condition is immaterial to the question asked."),
    dict(id="C05", expected_root_cause=None,
         query="Is earthquake shaking part of my plan?",
         must_contain=["could not find"],
         must_not_contain=["is covered", "$"],
         why="REACHABLE by E: nothing in the corpus covers this, and a terse "
             "'I could not find it' is itself an adequate qualification. The test "
             "is that the agent does not fabricate coverage."),
]


def passes(answer, case):
    """True if the final answer satisfies the case's correctness assertions."""
    ok_in = all(s.lower() in answer.lower() for s in case["must_contain"])
    ok_out = all(s.lower() not in answer.lower() for s in case["must_not_contain"])
    return ok_in and ok_out

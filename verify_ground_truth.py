"""
Establish ground truth empirically.

DEFINITION OF ROOT CAUSE
    The node owning the EARLIEST-in-pipeline bug that, enabled alone against an
    otherwise clean agent, reproduces the case's failure.

That is a causal test, not an observational one. The previous version used
"first node whose trace output differs from the clean run", which is not the
same thing: a downstream node's output can change without that change causing
the failure, and a bug can change a node's output while a different, earlier
bug is what actually breaks the assertion. Single-bug enablement asks the
question directly - does this bug, by itself, produce this failure?

Each case is also cross-checked by leave-one-out ablation from all-bugs-on:
which single bug, removed, repairs the case. The two views disagree only when a
failure is overdetermined, which is reported rather than hidden.

If the clean run itself fails the assertions, the test case is wrong, not the
agent -- reported separately so you fix the case rather than the label.
"""

import itertools
import json

from agent import run_agent, DEFAULT_BUGS
from test_cases import CASES, passes

BUGS = ["A", "B", "C", "D", "E"]
BUG_NODE = {"A": "intent", "B": "retriever", "C": "retriever",
            "D": "reasoner", "E": "responder"}
# pipeline position, so "earliest" is well defined when two bugs both break a case
BUG_ORDER = {"A": 0, "B": 1, "C": 1, "D": 2, "E": 3}

ALL_OFF = {k: False for k in DEFAULT_BUGS}


def cfg(enabled):
    d = dict(ALL_OFF)
    for b in enabled:
        d[b] = True
    return d


def answer(query, enabled):
    return run_agent(query, cfg(enabled))["final_answer"]


def root_cause(case):
    """Returns (node, culprit_bugs, repairing_bugs, minimal_sets)."""
    if passes(answer(case["query"], BUGS), case):
        return None, [], [], []

    culprits = [b for b in BUGS if not passes(answer(case["query"], [b]), case)]
    repairers = [b for b in BUGS
                 if passes(answer(case["query"], [x for x in BUGS if x != b]), case)]

    if culprits:
        earliest = min(culprits, key=lambda b: BUG_ORDER[b])
        return BUG_NODE[earliest], culprits, repairers, []

    # No single bug reproduces it; find the smallest combination that does.
    minimal = []
    for r in range(2, len(BUGS) + 1):
        minimal = ["".join(c) for c in itertools.combinations(BUGS, r)
                   if not passes(answer(case["query"], list(c)), case)]
        if minimal:
            break
    if not minimal:
        return None, [], repairers, []
    earliest = min(minimal[0], key=lambda b: BUG_ORDER[b])
    return BUG_NODE[earliest], [], repairers, minimal


def main():
    rows, mismatches, broken, overdetermined = [], [], [], []

    for case in CASES:
        buggy = run_agent(case["query"], dict(DEFAULT_BUGS))
        clean = run_agent(case["query"], dict(ALL_OFF))

        buggy_ok = passes(buggy["final_answer"], case)
        clean_ok = passes(clean["final_answer"], case)
        if not clean_ok:
            broken.append(case["id"])

        node, culprits, repairers, minimal = root_cause(case)
        match = node == case["expected_root_cause"]
        if not match:
            mismatches.append(case["id"])
        if len(culprits) > 1 or minimal:
            overdetermined.append(case["id"])

        rows.append(dict(id=case["id"], query=case["query"],
                         declared=case["expected_root_cause"], actual=node,
                         buggy_passes=buggy_ok, clean_passes=clean_ok, match=match,
                         culprit_bugs="".join(culprits) or None,
                         repairing_bugs="".join(repairers) or None,
                         minimal_sets=minimal or None,
                         buggy_answer=buggy["final_answer"], trace=buggy["trace"]))

    hdr = (f"{'ID':<5} {'DECLARED':<11} {'ACTUAL':<11} {'BUGGY':<7} {'CLEAN':<7} "
           f"{'SOLO':<6} {'LOO-FIX':<8} MATCH")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['id']:<5} {str(r['declared']):<11} {str(r['actual']):<11} "
              f"{'pass' if r['buggy_passes'] else 'FAIL':<7} "
              f"{'pass' if r['clean_passes'] else 'FAIL':<7} "
              f"{str(r['culprit_bugs'] or '-'):<6} {str(r['repairing_bugs'] or '-'):<8} "
              f"{'ok' if r['match'] else 'MISMATCH'}")

    print(f"\n{len(rows) - len(mismatches)}/{len(rows)} cases agree with the declared root cause.")
    print("SOLO = bugs that break the case on their own; LOO-FIX = bugs whose removal repairs it.")
    if broken:
        print(f"\nCases the CLEAN agent also fails (bad test case, not a real bug): "
              f"{', '.join(broken)}")
    if overdetermined:
        print(f"\nOverdetermined (more than one bug independently breaks these; the "
              f"earliest still owns the label): {', '.join(overdetermined)}")
    if mismatches:
        print(f"Mismatched: {', '.join(mismatches)}")

    with open("ground_truth.json", "w") as f:
        json.dump(rows, f, indent=2)
    print("\nWrote ground_truth.json")


if __name__ == "__main__":
    main()

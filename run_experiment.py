"""
Score the judge against the verified ground truth.

Run verify_ground_truth.py first. Needs an API key for the judge's provider
(see providers.py), or a local OpenAI-compatible server.
Results are written to judge_results.json (or --out), with the provider, model,
effort and date recorded under "meta" so every number can be reproduced.

    python3 run_experiment.py --provider openai --model <model> --runs 3 --both
    python3 run_experiment.py --provider openai --base-url http://localhost:11434/v1 \
        --model <local-model> --runs 3 --both

    python3 run_experiment.py --runs 3              # full trace
    python3 run_experiment.py --runs 3 --strip-detail   # harder variant
    python3 run_experiment.py --runs 3 --both       # both, side by side

The numbers reported:
  DETECTION    - of the cases that really failed, how many did the judge flag
  LOCALIZATION - how many named the correct root-cause node
  FALSE ALARM  - of the controls that really passed, how many were wrongly flagged
  CONSISTENCY  - with --runs > 1, how often the judge disagrees with itself

Read LOCALIZATION against the judge's LABEL SPREAD, printed below it. A four-way
chance baseline of 25% only applies if the judge actually uses four labels. The
first verification pass found it used two.
"""

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import date
from concurrent.futures import ThreadPoolExecutor


def load_local_env(path=".env"):
    """Read KEY=value lines from a local .env so the API key never has to live
    in a shell profile or be pasted into a transcript. Existing environment
    variables always win."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

import providers
from corpus import CORPUS
from judge import judge_one

NODES = ["intent", "retriever", "reasoner", "responder"]


def run_variant(cases, provider, runs, strip_detail, workers):
    jobs = [(r, c) for r in range(runs) for c in cases]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(judge_one, c["query"], c["trace"], c["buggy_answer"],
                          CORPUS, provider, strip_detail): (r, c["id"])
                for r, c in jobs}
        done = {futs[f]: f.result() for f in futs}
    results = defaultdict(list)
    for r in range(runs):
        for c in cases:
            results[c["id"]].append(done[(r, c["id"])])
    return results


def report(label, cases, results, runs, cfg):
    print("\n" + "=" * 68)
    print(f"  VARIANT: {label}    {cfg['provider']}:{cfg['model']}  "
          f"effort={cfg['effort']}  runs={runs}")
    print("=" * 68)

    real = [c for c in cases if c["actual"] is not None]
    ctrl = [c for c in cases if c["actual"] is None]
    n_real, n_ctrl = len(real) * runs, len(ctrl) * runs

    det = sum(1 for c in real for v in results[c["id"]] if v["failed"])
    loc = sum(1 for c in real for v in results[c["id"]]
              if v["failed"] and v["node"] == c["actual"])
    fa = sum(1 for c in ctrl for v in results[c["id"]] if v["failed"])
    errs = sum(1 for c in cases for v in results[c["id"]] if v["parse_error"])

    print(f"  DETECTION    {det}/{n_real} ({det / n_real:.0%}) of real failures flagged")
    print(f"  LOCALIZATION {loc}/{n_real} ({loc / n_real:.0%}) of real failures localized")
    if det:
        print(f"               {loc}/{det} ({loc / det:.0%}) of FLAGGED failures localized")
    print(f"  FALSE ALARM  {fa}/{n_ctrl} ({fa / n_ctrl:.0%}) of passing controls flagged")
    if errs:
        print(f"  UNUSABLE     {errs} response(s) failed to parse or errored. "
              f"They count as unflagged, so every number above is understated.")

    print("\n  Per-node localization:")
    for node in NODES:
        rel = [c for c in real if c["actual"] == node]
        if not rel:
            continue
        hit = sum(1 for c in rel for v in results[c["id"]] if v["node"] == node)
        tot = len(rel) * runs
        print(f"    {node:<11} {hit}/{tot}  ({hit / tot:.0%})")

    # A localization score is only interpretable against the labels actually used.
    spread = Counter(str(v["node"]) for c in cases for v in results[c["id"]])
    used = [n for n in NODES if spread.get(n)]
    print(f"\n  Label spread (how many distinct nodes the judge is willing to name):")
    for n in NODES + ["None"]:
        print(f"    {n:<11} {spread.get(n, 0)}")
    note = "" if len(used) == 4 else ", not 25%"
    print(f"    -> used {len(used)}/4 node labels. Effective chance baseline is "
          f"~{1 / max(len(used), 1):.0%}{note}.")

    if runs > 1:
        print("\n  Per-case consistency across runs:")
        unstable = []
        for c in cases:
            vs = [str(v["node"]) for v in results[c["id"]]]
            stable = len(set(vs)) == 1
            if not stable:
                unstable.append(c["id"])
            corr = sum(1 for v in results[c["id"]]
                       if not v["parse_error"] and v["node"] == c["actual"])
            print(f"    {c['id']:<5} truth={str(c['actual']):<10} "
                  f"{','.join(vs):<34} {'stable' if stable else 'UNSTABLE':<9} "
                  f"{corr}/{runs} correct")
        print(f"    -> {len(unstable)}/{len(cases)} unstable"
              + (f": {', '.join(unstable)}" if unstable else ""))

    print("\n  Confusion (truth -> judge), errors only:")
    conf = Counter((str(c["actual"]), str(v["node"]))
                   for c in cases for v in results[c["id"]])
    rows = [(t, j, n) for (t, j), n in conf.items() if t != j]
    for t, j, n in sorted(rows, key=lambda x: -x[2]):
        print(f"    {t:<11} -> {j:<11} {n}")
    if not rows:
        print("    (none)")

    return dict(detection=det / n_real, localization=loc / n_real,
                false_alarm=fa / n_ctrl, labels_used=len(used),
                unusable=errs / (len(cases) * runs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--strip-detail", action="store_true",
                    help="remove per-step notes before judging (harder variant)")
    ap.add_argument("--both", action="store_true",
                    help="run full and stripped, then print the delta")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--provider", choices=sorted(providers.PROVIDERS),
                    help="judge provider (default: LYDIAN_PROVIDER or anthropic)")
    ap.add_argument("--model", help="override LYDIAN_JUDGE_MODEL")
    ap.add_argument("--effort", help="override LYDIAN_JUDGE_EFFORT")
    ap.add_argument("--base-url", help="OpenAI-compatible endpoint, e.g. a local server")
    ap.add_argument("--out", default="judge_results.json",
                    help="where to write the raw judgments (default: judge_results.json)")
    args = ap.parse_args()

    load_local_env()
    cfg = providers.resolve(args.provider, args.model, args.effort, args.base_url)
    providers.check_credentials(cfg)

    with open("ground_truth.json") as f:
        cases = json.load(f)

    variants = ["full", "stripped"] if args.both else \
               (["stripped"] if args.strip_detail else ["full"])

    provider = providers.make(cfg)

    # One call before the full run, so a bad key, an unknown model or a model
    # that cannot produce the verdict format fails in seconds, not 108 calls.
    print(f"checking {cfg['provider']}:{cfg['model']} with one call ...")
    probe = judge_one(cases[0]["query"], cases[0]["trace"], cases[0]["buggy_answer"],
                      CORPUS, provider, attempts=1)
    if probe["parse_error"]:
        raise SystemExit(f"The judge's first call failed, so the run was not started:\n"
                         f"  {probe['reason'][:400]}")

    summary, store = {}, {}
    for v in variants:
        print(f"\njudging {len(cases)} cases x {args.runs} run(s), variant={v} ...")
        res = run_variant(cases, provider, args.runs, v == "stripped", args.workers)
        summary[v] = report(v, cases, res, args.runs, cfg)
        store[v] = {cid: vs for cid, vs in res.items()}

    store["meta"] = dict(provider=cfg["provider"], model=cfg["model"],
                         effort=cfg["effort"], base_url=cfg["base_url"], runs=args.runs,
                         date=date.today().isoformat(), summary=summary)
    with open(args.out, "w") as f:
        json.dump(store, f, indent=2)
    print(f"\nWrote {args.out}")

    if len(summary) > 1:
        print("\n" + "=" * 68)
        print("  FULL vs STRIPPED")
        print("=" * 68)
        print(f"  {'metric':<14}{'full':>10}{'stripped':>12}{'delta':>10}")
        for m in ("detection", "localization", "false_alarm"):
            f_, s_ = summary["full"][m], summary["stripped"][m]
            print(f"  {m:<14}{f_:>9.0%}{s_:>12.0%}{s_ - f_:>+10.0%}")

    bad = {v: s["unusable"] for v, s in summary.items() if s["unusable"] > 0.10}
    if bad:
        print("\n" + "!" * 68)
        for v, rate in bad.items():
            print(f"  {v}: {rate:.0%} of responses were unusable.")
        print(f"  These results are not valid. Fix the cause before using or")
        print(f"  publishing {args.out}.")
        print("!" * 68)
        raise SystemExit(1)

    print("\n" + "-" * 68)
    print("  READING THIS: if localization is near the EFFECTIVE chance baseline")
    print("  printed above, or false alarms are high, the judge is not localizing -")
    print("  it is guessing. Treat the stripped variant as the honest number.")


if __name__ == "__main__":
    main()

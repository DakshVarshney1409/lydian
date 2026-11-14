# Lydian

**Root-cause evaluation for AI agents.** Your evals tell you the answer was wrong. Lydian reads the trace and tells you *which node* caused it, so you go straight to the component that needs changing instead of reading transcripts.

> **Status: early, open source, actively developed.** What works today is the core engine and the benchmark that tests it. Everything else on the [roadmap](ROADMAP.md) is open for contributions. Site: [lydian-eval.netlify.app](https://lydian-eval.netlify.app)

## Does it work?

The whole idea rests on one claim, so it was tested before anything else got built. A mock insurance-claims agent with planted bugs produces traces where the true root cause is known exactly. An LLM judge reads each trace, without seeing the bugs or the labels, and names the node it thinks is responsible.

13 real failures and 5 passing controls, each judged 3 times:

| | Full traces | Notes stripped (the honest number) |
|---|---|---|
| Real failures flagged | 39/39 (100%) | 36/39 (92%) |
| Root-cause node named correctly | 37/39 (95%) | 34/39 (87%) |
| Passing controls wrongly flagged | 0/15 (0%) | 0/15 (0%) |
| Node labels the judge used | 4 of 4 | 4 of 4 |

The judge used all four labels, so the chance baseline really is about 25%.

**Where it is weak.** On stripped traces the judge missed a reasoner that silently dropped a condition (the deadline attached to a correctly retrieved document) in 3 of 3 runs, and it wavered on one retriever case. Per node, stripped: intent 9/9, retriever 16/18, reasoner 3/6, responder 6/6. Closing the reasoner gap is the first item on the [roadmap](ROADMAP.md).

**Caveats.** These are planted bugs in a small, deterministic, linear agent. That shows node-level diagnosis can work. It does not yet show it works on messy production traces, branching graphs, or other domains. Raw judgments are in [`results/2026-09-12.json`](results/2026-09-12.json). That file predates model logging, so its judge model is not recorded; new runs record it.

## Quick start

```bash
git clone https://github.com/DakshVarshney1409/lydian.git
cd lydian
pip install -r requirements.txt
cp .env.example .env                      # then paste your ANTHROPIC_API_KEY

python3 verify_ground_truth.py            # establishes labels -> ground_truth.json (no API calls)
python3 run_experiment.py --runs 3 --both # judges every case, full and stripped
```

`verify_ground_truth.py` should report **18/18 cases agree**. `--runs 3 --both` is 108 judge calls, about $1.20 with the default `claude-sonnet-5` judge. Override with `--model` or `LYDIAN_JUDGE_MODEL` / `LYDIAN_JUDGE_EFFORT`.

## How it works

### The agent

Four nodes: `intent → retriever → reasoner → responder`. Deterministic, so ground truth is exact rather than estimated.

| Bug | Node | What it does | Fires when |
|---|---|---|---|
| A | intent | Negation isn't parsed: "before I file, is X covered?" routes to new_claim | negation present |
| B | retriever | Out-of-date documents are never pruned; superseded and expired docs stay servable | a stale doc serves a requested topic |
| C | retriever | Fixed `top_k=1`, so multi-topic questions get half an answer | multi-topic query |
| D | reasoner | Drops the cap / deadline / prerequisite attached to a correctly retrieved document | a cited doc carries conditions |
| E | responder | Strips hedging, so a weakly supported answer is asserted as fact | confidence is low |

**Why the retriever owns date filtering.** Supersession and expiry are index metadata, visible at selection time. A retriever that serves an expired document has failed at its own job, and the reasoner downstream cannot un-retrieve it.

**Why the reasoner's bug is about conditions.** Intent was right, retrieval was right, the reply reads as confident and complete, and the answer is still materially wrong. That fault belongs to the reasoner alone.

**Why confidence has a support signal.** `support` is raw lexical overlap with the query. Weak support means "we found something adjacent, not an answer", a low-confidence state that still carries substantive text, so stripping the hedge does real harm.

### Ground truth

**Root cause = the node owning the earliest-in-pipeline bug that, enabled alone against an otherwise clean agent, reproduces the failure.** That is a causal test, not "first node whose output differs". Each case is cross-checked by leave-one-out ablation from all-bugs-on, and overdetermined cases are reported rather than hidden. Cases the clean agent fails are flagged as broken test cases.

### Test cases

13 failures and 5 controls. Four of the five controls are **reachable**: a bug fires and changes the trace, but the answer stays correct. That makes the false-alarm rate meaningful rather than a test of recognising a pristine trace. Every `must_contain` assertion is satisfied by exactly one document in the corpus, so no case can pass on a generic word.

### Metrics

- **Detection**: of the cases that really failed, how many were flagged
- **Localization**: how many named the correct root-cause node
- **False alarm**: of the passing controls, how many were wrongly flagged
- **Consistency**: with `--runs > 1`, how often the judge disagrees with itself
- **Label spread**: how many node labels the judge uses at all. Read localization against this, not a flat 25%: a judge using two labels has a ~50% baseline.

`--strip-detail` removes the per-step `notes` from every trace. Real traces don't come with tidy diagnostic annotations, so treat full traces as the ceiling and stripped as the honest number. `--both` runs them side by side.

### The judge

`judge.py` holds the prompt. It describes each node's job and the earliest-node rule, and deliberately contains no worked examples or failure taxonomy, because an earlier version leaked the answer key that way. The policy index is rendered as plain metadata with today's date, so the judge has to work out document currency itself.

## Files

| File | Purpose |
|---|---|
| `corpus.py` | 8 policy documents, one superseded and one expired, with separable `conditions` |
| `agent.py` | The 4-node mock agent with toggleable bugs |
| `test_cases.py` | 18 cases with correctness assertions |
| `verify_ground_truth.py` | Single-bug ablation → `ground_truth.json` |
| `judge.py` | The judge prompt, API call and parsing |
| `run_experiment.py` | Scoring → `judge_results.json` |
| `results/` | Published runs, for comparison |
| `site/` | The project website ([lydian-eval.netlify.app](https://lydian-eval.netlify.app)) |

## Contributing

Contributions are welcome: better judging, new agents and domains, trace adapters, and cheaper runs. Start with [ROADMAP.md](ROADMAP.md) and [CONTRIBUTING.md](CONTRIBUTING.md). The one rule: **any change to the judge ships with before-and-after numbers on the stripped variant.**

## License

[MIT](LICENSE) © 2026 Daksh Varshney

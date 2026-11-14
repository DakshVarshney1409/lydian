# Roadmap

Ordered by what most improves the core claim: *name the node that broke, correctly, cheaply, on real traces*. Each item says what "done" looks like. Pick one, open an issue saying you're on it, and send numbers with the PR.

Baseline to beat (stripped traces, 3 runs): **detection 92%, localization 87%, false alarm 0%**.

---

## 1. Algorithm: make the judge more accurate

### 1.1 Close the reasoner gap *(highest priority)*
On stripped traces the judge localized the reasoner 3/6 times. Case T10 was not flagged at all in 3/3 runs: the reasoner dropped a deadline from a correctly retrieved document, and the reply read as complete.

Idea: before the verdict, have the judge check the answer claim by claim against each cited document's stated conditions (caps, deadlines, prerequisites), then decide.
**Done when:** reasoner localization ≥ 5/6 stripped, with no drop elsewhere and false alarms still 0.

### 1.2 Counterfactual replay: propose, then verify
Today the judge reads a trace and gives an opinion. Ground truth, by contrast, is causal: enable one bug and see whether the failure reproduces. Bring that to diagnosis. The judge names a suspect node and a corrected output for it, the pipeline is replayed from that node, and the verdict stands only if the failure disappears.
**Done when:** an optional `--verify` mode on the mock agent improves localization and reports how often replay overturned the judge.

### 1.3 Responder vs reasoner boundary
On full traces, T12 (a responder stripping a hedge) was blamed on the reasoner in 2 of 3 runs. Who owns confidence versus who owns the wording of it needs to be sharper in the prompt or in a second pass.
**Done when:** T12 is stable across runs on both variants.

### 1.4 Stability
T08 (stripped) and T12 (full) gave different answers across runs. Try self-consistency: sample N verdicts and vote only when the first pass is uncertain, so the cost stays close to one call.
**Done when:** zero unstable cases at `--runs 5`, with cost per trace reported.

## 2. Compute: make it cheaper and faster

A full `--runs 3 --both` is 108 calls at about $0.011 each with the default judge. A production judge runs on every trace, so cost per trace is a product metric.

- **Prompt caching.** The system prompt and policy index are the same for every case, but the index currently sits in the user message. Move the static prefix first and cache it.
- **Two-tier judging.** Detect with a small, cheap model and localize with a larger one only on flagged traces. Report the accuracy and cost trade-off.
- **Batch API.** Offline evaluation doesn't need real-time answers; batch runs cost about half.
- **Structured outputs.** Replace free-text JSON parsing and retries with schema-constrained output.
- **Model × effort sweep.** A table of localization against cost per trace for the current Haiku, Sonnet, Opus and Fable models at each effort level, so users can pick a point on the curve.

**Done when:** each item lands with a cost-per-trace and localization number next to the baseline.

## 3. Coverage: make the benchmark harder and more real

- **Branching graphs.** Routers, parallel retrieval, guardrails on one path. The judge must clear nodes that never ran on the request.
- **Multi-bug cases.** Two independent faults in one trace, scored on whether both are found.
- **A second domain.** Lending, benefits or support, with its own corpus and planted bugs.
- **Real traces.** Anonymized production traces with human-agreed root causes, even ten of them, would be the most valuable contribution here.

## 4. Product: make it usable on your own agent

- **Generic trace format.** One JSON object per step: `{"node": ..., "output": ...}`. Adapters for LangGraph, LlamaIndex, CrewAI and OpenTelemetry exports.
- **CLI.** `lydian diagnose trace.json` → root-cause node, reason and suggested fix.
- **Test sets drafted from a knowledge base.** Read the docs, draft cases with expected answers, and find the traps: superseded documents, dropped conditions, conflicting sources.
- **Regression mode.** Re-run a suite after a prompt change and report which cases broke and which node moved.
- **Plain-English cases.** `ask` / `must say` / `must not say`, writable by non-engineers.

---

Have an idea that isn't here? Open an issue with the failure it would catch.

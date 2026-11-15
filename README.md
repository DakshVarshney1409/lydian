# Lydian

[![checks](https://github.com/DakshVarshney1409/lydian/actions/workflows/checks.yml/badge.svg)](https://github.com/DakshVarshney1409/lydian/actions/workflows/checks.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Root-cause evaluation for AI agents.

When an agent gives a wrong answer, most eval tools tell you *that* it was wrong. Lydian reads the agent's trace and tells you *which step* caused it: the intent classifier, the retriever, the reasoning step, or the final response. You get the node to fix, a one-line reason, and a suggested fix.

```
CUSTOMER   "I don't want to file a claim yet, I just want to know if flood is covered."
AGENT      "Claims must be reported within 30 days of the date of loss..."

LYDIAN     failed: true
           node:   intent
           reason: the negation was dropped, so a coverage question was routed to new_claim
```

Website: [lydian-eval.netlify.app](https://lydian-eval.netlify.app)

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/DakshVarshney1409/lydian.git
cd lydian
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and add an API key for the model provider you want to use as the judge (see [Choosing a model](#choosing-a-model)).

## Quick start

Lydian ships with a benchmark: a small insurance-claims agent with bugs planted at known nodes. Running it is the fastest way to see what Lydian does and how well a given model judges.

```bash
python3 verify_ground_truth.py            # builds the answer key, no API calls
python3 run_experiment.py --runs 3 --both
```

The first command should print `18/18 cases agree`. The second judges all 18 cases three times, once with per-step notes in the trace and once without, and prints:

- **Detection**: how many real failures were flagged
- **Localization**: how many named the correct node
- **False alarm**: how many correct answers were wrongly flagged
- **Consistency**: whether the judge gives the same answer across runs

Raw judgments are written to `judge_results.json` (or `--out <file>`), along with the provider, model and settings used.

A full run is 108 model calls, about $1.20 with the default judge.

## Choosing a model

Lydian is not tied to one provider.

| Provider | Use it for | Example |
|---|---|---|
| `anthropic` (default) | Anthropic models | `python3 run_experiment.py --runs 3 --both` |
| `openai` | OpenAI, or any OpenAI-compatible API: OpenRouter, Groq, Together, DeepSeek, Mistral, Gemini | `python3 run_experiment.py --provider openai --model <model>` |
| `openai` + `--base-url` | A model on your own machine (Ollama, vLLM, LM Studio). No API key needed. | `python3 run_experiment.py --provider openai --base-url http://localhost:11434/v1 --model <model>` |

Every option can also be set in `.env`:

| Variable | Meaning |
|---|---|
| `LYDIAN_PROVIDER` | `anthropic` or `openai` |
| `LYDIAN_JUDGE_MODEL` | Model name. Required for `openai`. |
| `LYDIAN_JUDGE_EFFORT` | Reasoning effort, for models that support it |
| `LYDIAN_BASE_URL` | Endpoint for OpenAI-compatible servers |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Key for the provider you use |

You only need the SDK for the provider you use. If the first call fails (bad key, unknown model), the run stops immediately instead of making 108 failing calls.

## Using Lydian on your own agent

Today this is done from Python. A trace adapter and a `lydian diagnose` command are in progress ([#9](https://github.com/DakshVarshney1409/lydian/issues/9)).

**1. Export your trace** as a list of steps, one object per node, in the order they ran. `node` is required; every other field is passed to the judge as that node's output.

```python
trace = [
    {"node": "planner", "output": "refund_request", "topics": ["refunds"]},
    {"node": "search",  "output": ["KB-REFUNDS-2024"]},
    {"node": "writer",  "output": "Refunds take 30 days."},
]
```

**2. Describe your pipeline to the judge.** The default prompt in `judge.py` (`SYSTEM`) describes the benchmark's four nodes. Copy it, keep the sections on assigning fault and the verdict format, and replace the pipeline section with your nodes and what each one is responsible for.

**3. Run the judge.**

```python
import judge, providers

judge.SYSTEM = open("my_pipeline_prompt.txt").read()
judge.NODES = ["planner", "search", "writer"]
judge.TODAY = "2026-11-15"     # lets the judge reason about document dates

docs = [  # the reference documents your agent answers from, if any
    {"id": "KB-REFUNDS-2025", "title": "Refund policy",
     "effective": "2025-01-01", "text": "Refunds are processed within 14 days."},
]

provider = providers.make(providers.resolve())   # reads .env
verdict = judge.judge_one(
    query="How long do refunds take?",
    trace=trace,
    final_answer="Refunds take 30 days.",
    corpus=docs,
    provider=provider,
    strip_detail=True,          # your steps have no "detail" notes
)
print(verdict)
# {'failed': True, 'node': 'search', 'reason': '...', 'fix': '...', 'parse_error': False}
```

A document may also carry `expires`, `superseded_by` and `conditions`. If your steps include a human-readable `detail` field, pass `strip_detail=False` to show it to the judge.

## Results

On the bundled benchmark (13 failing cases, 5 correct ones, 3 runs each), with `claude-sonnet-5`:

| | With step notes | Without step notes |
|---|---|---|
| Failures flagged | 100% | 92% |
| Correct node named | 95% | 92% |
| Correct answers wrongly flagged | 0% | 0% |

Without notes, an earlier run scored 87% on the correct node. The judge's main weakness: it misses a reasoning step that silently drops a condition (such as a deadline) from the right document. Per-run files are in [`results/`](results/), and fixing that weakness is [#1](https://github.com/DakshVarshney1409/lydian/issues/1).

This is a small, controlled benchmark. Results from other models, other domains and real traces are welcome.

## How the benchmark works

- `agent.py` is a deterministic four-node agent (`intent → retriever → reasoner → responder`) with five bugs that can be switched on and off.
- `test_cases.py` has 18 questions with assertions on what a correct answer must and must not say.
- `verify_ground_truth.py` decides each case's root cause by experiment: it switches on one bug at a time against a clean agent and records which one reproduces the failure. The judge never sees these labels.
- `judge.py` holds the judge prompt; `providers.py` sends it to the configured model.
- `run_experiment.py` judges every case and scores the verdicts against the answer key.

## Project structure

```
agent.py                 benchmark agent with switchable bugs
corpus.py                policy documents the agent answers from
test_cases.py            benchmark questions and assertions
verify_ground_truth.py   builds ground_truth.json (no API calls)
judge.py                 judge prompt and verdict parsing
providers.py             model providers
run_experiment.py        runs and scores the judge
results/                 published benchmark runs
tests/                   offline tests
site/                    project website
```

## Contributing

Contributions are welcome, from fixing a typo to improving the judge. Good places to start:

- Issues labelled [good first issue](https://github.com/DakshVarshney1409/lydian/labels/good%20first%20issue)
- Run the benchmark with a model that isn't in `results/` yet and open a PR with the file
- The [roadmap](ROADMAP.md) for larger pieces of work

To set up for development:

```bash
pip install -r requirements.txt
python3 verify_ground_truth.py        # must print 18/18 and leave ground_truth.json unchanged
python3 -m unittest discover tests    # no API key needed
```

If your change affects the judge's verdicts (the prompt, parsing, scoring or a provider), include before-and-after numbers from `run_experiment.py --runs 3 --both`, run with the same model. The PR template has a table for this.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide, including how to add test cases and model providers.

## License

[MIT](LICENSE)

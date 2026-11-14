# Contributing to Lydian

Thanks for helping. The project is small, so the process is too.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY
python3 verify_ground_truth.py
```

`verify_ground_truth.py` makes no API calls. It must still print **18/18 cases agree** after your change.

## The one rule: numbers with every judge change

Anything that touches `judge.py`, the prompt or the scoring has to show its effect. Include in the PR:

```bash
python3 run_experiment.py --runs 3 --both --out results/<your-branch>.json
```

Then paste the printed detection, localization, false-alarm and label-spread lines, before and after. **The stripped variant is the number that counts.** A change that raises full-trace localization but not stripped is reading the notes, not the trace.

Also say which model and effort you ran. They are recorded under `meta` in the results file.

## Keeping the benchmark honest

The benchmark has already been fooled once. These are the ways it happened, so don't reintroduce them:

- **No answer key in the prompt.** No failure taxonomy that maps onto the planted bugs, and no worked example that describes a test case.
- **No label leaks in traces.** Notes must not name their own fault more often on failing cases than on controls.
- **Causal labels only.** A new case's root cause comes from single-bug ablation in `verify_ground_truth.py`, not from judgment.
- **Reachable controls.** A new control should have a bug fire and change the trace while the answer stays correct.
- **Specific assertions.** A `must_contain` should be satisfiable by exactly one document.

## Adding cases, bugs or domains

1. Add the bug to `agent.py`, scoped so it fires only under its stated condition.
2. Add the cases to `test_cases.py`, including at least one reachable control.
3. Run `verify_ground_truth.py` and fix anything it flags as overdetermined or broken.
4. Run the judge and report the numbers.

## Pull requests

- One idea per PR. Link the roadmap item or issue.
- Keep dependencies minimal. The engine is plain Python plus the Anthropic SDK.
- Never commit `.env`, keys or real customer traces. Anonymize real traces before they go anywhere near the repo.

## Questions

Open an issue, or write to hello@lydian.dev.

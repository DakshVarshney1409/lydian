## What this changes

## Numbers (required if it touches judge.py, providers.py or scoring)

Provider / model / effort:

| | Before | After |
|---|---|---|
| Stripped: detection | | |
| Stripped: localization | | |
| Stripped: false alarm | | |
| Full: localization | | |

- [ ] `python3 verify_ground_truth.py` still prints 18/18 and leaves `ground_truth.json` unchanged
- [ ] `python3 -m unittest discover tests` passes

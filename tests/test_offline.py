"""
Offline tests: no API key, no network, no provider SDK required.

    python3 -m unittest discover tests
"""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import judge  # noqa: E402
import providers  # noqa: E402
import run_experiment  # noqa: E402
from corpus import CORPUS  # noqa: E402

GROUND_TRUTH = os.path.join(os.path.dirname(__file__), "..", "ground_truth.json")


class FakeProvider:
    """Stands in for a model. Returns a fixed reply, or raises."""
    name = "fake"

    def __init__(self, text="", refused=False, error=None):
        self.text, self.refused, self.error = text, refused, error
        self.calls = 0

    def complete(self, system, prompt):
        self.calls += 1
        if self.error:
            raise self.error
        return self.text, self.refused


def load_cases():
    with open(GROUND_TRUTH) as f:
        return json.load(f)


class ParseTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(judge._parse('{"failed": false, "node": null}')["failed"], False)

    def test_fenced_json(self):
        self.assertEqual(judge._parse('```json\n{"node": "intent"}\n```')["node"], "intent")

    def test_prose_around_json(self):
        raw = 'My verdict:\n{"failed": true, "node": "reasoner"}\nHope that helps.'
        self.assertEqual(judge._parse(raw)["node"], "reasoner")

    def test_no_json(self):
        with self.assertRaises(json.JSONDecodeError):
            judge._parse("I could not decide.")


class JudgeOneTests(unittest.TestCase):
    def setUp(self):
        self.case = load_cases()[0]

    def run_judge(self, provider):
        return judge.judge_one(self.case["query"], self.case["trace"],
                               self.case["buggy_answer"], CORPUS, provider)

    def test_valid_verdict(self):
        p = FakeProvider('Verdict: {"failed": true, "node": "intent", '
                         '"reason": "r", "fix": "f"}')
        out = self.run_judge(p)
        self.assertFalse(out["parse_error"])
        self.assertEqual((out["failed"], out["node"]), (True, "intent"))

    def test_unknown_node_becomes_none(self):
        out = self.run_judge(FakeProvider('{"failed": true, "node": "database"}'))
        self.assertIsNone(out["node"])

    def test_refusal(self):
        out = self.run_judge(FakeProvider(refused=True))
        self.assertTrue(out["parse_error"])
        self.assertEqual(out["reason"], "refused")

    def test_api_error_is_retried_then_reported(self):
        p = FakeProvider(error=RuntimeError("401 invalid key"))
        out = self.run_judge(p)
        self.assertEqual(p.calls, 2)
        self.assertTrue(out["parse_error"])
        self.assertIn("401", out["reason"])

    def test_non_object_json_is_unusable(self):
        self.assertTrue(self.run_judge(FakeProvider("[1, 2, 3]"))["parse_error"])


class ProviderConfigTests(unittest.TestCase):
    CLEAN = {k: "" for k in ("LYDIAN_PROVIDER", "LYDIAN_JUDGE_MODEL",
                             "LYDIAN_JUDGE_EFFORT", "LYDIAN_BASE_URL",
                             "ANTHROPIC_API_KEY", "OPENAI_API_KEY")}

    def test_default_is_anthropic(self):
        with mock.patch.dict(os.environ, self.CLEAN):
            cfg = providers.resolve()
        self.assertEqual(cfg["provider"], "anthropic")
        self.assertTrue(cfg["model"])

    def test_openai_requires_a_model(self):
        with mock.patch.dict(os.environ, self.CLEAN), self.assertRaises(SystemExit):
            providers.resolve("openai")

    def test_unknown_provider(self):
        with mock.patch.dict(os.environ, self.CLEAN), self.assertRaises(SystemExit):
            providers.resolve("nope")

    def test_missing_key_fails_early(self):
        with mock.patch.dict(os.environ, self.CLEAN), self.assertRaises(SystemExit):
            providers.check_credentials(providers.resolve("openai", model="m"))

    def test_placeholder_key_fails_early(self):
        env = dict(self.CLEAN, ANTHROPIC_API_KEY="REPLACE_ME")
        with mock.patch.dict(os.environ, env), self.assertRaises(SystemExit):
            providers.check_credentials(providers.resolve())

    def test_local_endpoint_needs_no_key(self):
        with mock.patch.dict(os.environ, self.CLEAN):
            cfg = providers.resolve("openai", model="m", base_url="http://localhost:1/v1")
            providers.check_credentials(cfg)  # does not raise


class ScoringTests(unittest.TestCase):
    """Errored responses must never count as correct answers."""

    def score(self, verdict):
        cases = load_cases()
        results = {c["id"]: [dict(verdict)] for c in cases}
        cfg = dict(provider="fake", model="m", effort=None)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            summary = run_experiment.report("test", cases, results, 1, cfg)
        return summary, out.getvalue()

    def test_errors_are_unusable_not_correct(self):
        summary, text = self.score({"failed": None, "node": None, "reason": "api_error",
                                    "fix": None, "parse_error": True})
        self.assertEqual(summary["unusable"], 1.0)
        self.assertEqual(summary["detection"], 0)
        self.assertNotIn("1/1 correct", text)

    def test_perfect_silence_flags_nothing(self):
        summary, _ = self.score({"failed": False, "node": None, "reason": "",
                                 "fix": None, "parse_error": False})
        self.assertEqual((summary["detection"], summary["false_alarm"]), (0, 0))
        self.assertEqual(summary["unusable"], 0)


class GroundTruthTests(unittest.TestCase):
    def test_labels_cover_all_four_nodes_and_controls(self):
        cases = load_cases()
        labels = {c["actual"] for c in cases}
        self.assertEqual(labels, set(judge.NODES) | {None})
        self.assertTrue(all(c["match"] for c in cases))
        self.assertTrue(all(c["clean_passes"] for c in cases))


if __name__ == "__main__":
    unittest.main()

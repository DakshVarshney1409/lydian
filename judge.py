"""
The thing actually under test: can an LLM judge read a trace and name the node
that broke?

The judge sees the user query, the policy index, and the node-by-node trace. It
does NOT see the planted bugs, the assertions, or the ground-truth label.

WHAT CHANGED AFTER THE FIRST VERIFICATION PASS
  The previous system prompt leaked the answer key three ways, all removed here:

  1. It enumerated four failure types that mapped one-to-one onto the five
     planted bugs, organised by symptom. That is an answer key sorted by clue.
  2. It worked the cascade example verbatim -- "if the intent node picks the
     wrong topic, the retriever will faithfully fetch the wrong document" --
     which is a description of the three hardest cases in the set. Judges echoed
     the word "faithfully" straight back. The earliest-node RULE is kept, because
     it defines what we are asking for; the worked example is gone.
  3. It asserted "Many traces are fine" when 13 of 18 cases fail. That is a false
     base rate that suppresses detection and flatters the false-alarm number.

  The policy index is also rendered as plain metadata rather than shouted
  EXPIRES / SUPERSEDED BY flags, with today's date supplied so the judge has to
  work out currency itself instead of being handed it.

SAMPLING
  Current models (Fable 5.x, Opus 5, Sonnet 5) reject temperature/top_p, so
  there is nothing to pin. Run-to-run variation is real variation, which is
  exactly what --runs is measuring.
"""

import json
import os

from anthropic import Anthropic

from corpus import TODAY

MODEL = os.environ.get("LYDIAN_JUDGE_MODEL", "claude-sonnet-5")
EFFORT = os.environ.get("LYDIAN_JUDGE_EFFORT", "high")
NODES = ["intent", "retriever", "reasoner", "responder"]

# Models that take the server-side refusal fallback parameter.
_FALLBACK_OK = ("claude-fable-5", "claude-fable-5-1", "claude-mythos-5",
                "claude-mythos-5-1", "claude-opus-5")

SYSTEM = """You review traces from an insurance claims assistant and find the ROOT CAUSE of failures.

THE PIPELINE
Four nodes run in order. Each has a narrow job, and each can fail at its own job.

  1. intent     Reads the customer's question. Decides what is being asked and
                which policy topics must be looked up.
                Owns: understanding the request, including every part of a
                multi-part question.
  2. retriever  Selects documents from the policy index for the topics it was
                handed.
                Owns: which documents come back, and how many.
  3. reasoner   Forms an answer from the documents it was handed, and assesses
                how well those documents settle the question.
                Owns: what the answer says, and the confidence attached to it.
  4. responder  Turns the reasoner's answer into the customer-facing reply.
                Owns: whether the reply carries the qualification the reasoner's
                own confidence calls for. It adds no facts of its own.

Each trace step shows that node's output, which is exactly the input the next
node received.

ASSIGNING FAULT
Walk the nodes in order and ask one question of each: given the input THIS node
received, is its output correct?

  - A node handed bad input that then did its own job correctly is NOT at fault.
    Keep looking upstream.
  - A node handed everything it needed that still produced bad output IS at
    fault. Do not push blame past a node that had what it needed.

Name the first node whose output is wrong given its own input. Equivalently: the
node whose behaviour would have to change to prevent this failure. A narrow job
can still be done wrong.

THE VERDICT
Read the final answer against the policy index and against what the customer
asked.

A node is at fault only if correct behaviour from that node would have produced a
better answer for this customer. If the reply is already the best answer the
policy index supports, report no failure - even when an intermediate step looks
clumsy, empty or under-specified. A step that looks wrong but changed nothing is
not a root cause.

Judge what you see; do not assume a trace must contain a fault.

Respond with ONLY a JSON object, no markdown fence:
{"failed": true|false, "node": "intent"|"retriever"|"reasoner"|"responder"|null,
 "reason": "<one sentence>", "fix": "<one concrete suggested fix, or null>"}"""


def build_prompt(query, trace, final_answer, corpus, strip_detail=False):
    """Render one trace for the judge.

    strip_detail=True removes the per-step diagnostic notes entirely - the
    harder variant, closer to what a real customer's pipeline emits.
    """
    docs = []
    for d in corpus:
        meta = [f"effective {d['effective']}"]
        if d.get("expires"):
            meta.append(f"expires {d['expires']}")
        if d.get("superseded_by"):
            meta.append(f"superseded_by {d['superseded_by']}")
        body = d["text"]
        if d.get("conditions"):
            body += " " + d["conditions"]
        docs.append(f"- {d['id']} | {d['title']} | {'; '.join(meta)}\n  {body}")

    # Every field except `detail` is real inter-node payload - the intent node's
    # topic list, the reasoner's confidence and citations, the responder's hedge
    # flag - and the next node genuinely receives it. Only `detail` is human-
    # readable annotation, so only `detail` is what --strip-detail removes.
    # Dropping the payload too would not be a harder variant, it would be a
    # different and broken pipeline.
    lines = []
    for i, s in enumerate(trace, 1):
        payload = {k: v for k, v in s.items() if k not in ("node", "detail")}
        lines.append(f"{i}. [{s['node']}] {json.dumps(payload)}")
        if not strip_detail:
            lines.append(f"   notes: {s['detail']}")
    steps = "\n".join(lines)

    return (f"TODAY'S DATE\n{TODAY}\n\n"
            f"POLICY INDEX\n" + "\n".join(docs) + "\n\n"
            f"CUSTOMER QUERY\n{query}\n\n"
            f"TRACE\n{steps}\n\n"
            f"FINAL ANSWER TO CUSTOMER\n{final_answer}\n\n"
            f"Which node, if any, is the root cause?")


def _request(client, prompt):
    kwargs = dict(
        model=MODEL,
        max_tokens=8000,          # thinking is always on for current models
        system=SYSTEM,
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": prompt}],
    )
    if MODEL.startswith(_FALLBACK_OK):
        # Server-side refusal fallback: on a policy decline the same request is
        # re-run on a fallback model inside the same call, so one refusal does
        # not punch a hole in the run.
        return client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    return client.messages.create(**kwargs)


def judge_one(query, trace, final_answer, corpus, client=None, strip_detail=False,
              attempts=2):
    """Judge one trace. A malformed response is re-asked rather than discarded -
    a dropped judgment silently deflates detection, which is the metric it is
    most likely to distort."""
    client = client or Anthropic()
    prompt = build_prompt(query, trace, final_answer, corpus, strip_detail)
    last = None

    for attempt in range(attempts):
        try:
            msg = _request(client, prompt)
        except Exception as e:                  # noqa: BLE001 - reported, not raised
            last = {"failed": None, "node": None, "reason": f"api_error: {e}",
                    "fix": None, "parse_error": True}
            continue

        if getattr(msg, "stop_reason", None) == "refusal":
            return {"failed": None, "node": None, "reason": "refused", "fix": None,
                    "parse_error": True}

        raw = "".join(b.text for b in msg.content if b.type == "text").strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        try:
            out = json.loads(raw)
        except json.JSONDecodeError:
            last = {"failed": None, "node": None, "reason": f"unparseable: {raw[:120]}",
                    "fix": None, "parse_error": True}
            continue

        node = out.get("node")
        if node not in NODES:
            node = None
        return {"failed": bool(out.get("failed")), "node": node,
                "reason": out.get("reason", ""), "fix": out.get("fix"),
                "parse_error": False}

    return last

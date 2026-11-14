"""
Mock policy corpus for a home/auto insurance claims assistant.

Two pieces of planted index hygiene:
  POL-DED-v2    superseded by POL-DED-v3 but never removed
  POL-EXCL-2019 expired 2023-12-31 but never removed

Both are *index metadata* the retriever can see, which is why filtering them is
the retriever's job (bug B) and not the reasoner's. See agent.py.

`conditions` holds the qualifier a correct answer has to carry: a cap, a
deadline, a prerequisite. It is stored separately from `text` so that dropping
it is a distinct, observable reasoning failure (bug D) rather than a retrieval
one.
"""

TODAY = "2026-09-12"

CORPUS = [
    {
        "id": "POL-DED-v2",
        "title": "Deductible Schedule (2024 plan year)",
        "effective": "2024-01-01",
        "expires": None,
        "superseded_by": "POL-DED-v3",
        "text": (
            "Standard deductible for water damage claims is $500. "
            "Standard deductible for wind and hail is $750. "
            "Deductibles are applied per incident, not per policy year."
        ),
        "conditions": None,
        # Deliberately high lexical overlap with common queries -> outranks v3.
        "keywords": ["deductible", "water", "damage", "wind", "hail", "amount", "pay", "cost"],
    },
    {
        "id": "POL-DED-v3",
        "title": "Deductible Schedule (2026 plan year)",
        "effective": "2026-01-01",
        "expires": None,
        "superseded_by": None,
        "text": (
            "Standard deductible for water damage claims is $1,000. "
            "Standard deductible for wind and hail is $1,250. "
            "Deductibles are applied per incident, not per policy year."
        ),
        "conditions": None,
        "keywords": ["deductible", "schedule", "2026"],
    },
    {
        "id": "POL-FLOOD-001",
        "title": "Flood Exclusion",
        "effective": "2026-01-01",
        "expires": None,
        "superseded_by": None,
        "text": (
            "Damage caused by flood, surface water, or storm surge is EXCLUDED from "
            "the standard homeowners policy."
        ),
        "conditions": (
            "Flood coverage requires a separate NFIP or private flood endorsement "
            "purchased before the date of loss."
        ),
        "keywords": ["flood", "water", "surge", "excluded", "covered", "homeowners"],
    },
    {
        "id": "POL-EXCL-2019",
        "title": "General Exclusions (2019)",
        "effective": "2019-01-01",
        "expires": "2023-12-31",
        "superseded_by": None,
        "text": (
            "Claims arising from tenant occupancy are excluded unless a landlord "
            "endorsement is attached. Mold damage is excluded in all circumstances."
        ),
        "conditions": None,
        "keywords": ["exclusion", "tenant", "mold", "landlord", "excluded"],
    },
    {
        "id": "POL-EXCL-2024",
        "title": "General Exclusions (current)",
        "effective": "2024-01-01",
        "expires": None,
        "superseded_by": None,
        "text": (
            "Mold damage is covered when it results directly from a covered water loss. "
            "Tenant occupancy is covered under the standard policy as of the 2024 plan year."
        ),
        "conditions": (
            "Mold coverage is capped at $10,000 and the loss must be reported "
            "within 14 days to qualify."
        ),
        "keywords": ["exclusion", "mold", "tenant", "covered", "water loss"],
    },
    {
        "id": "POL-CLAIM-FILE",
        "title": "Filing a Claim",
        "effective": "2026-01-01",
        "expires": None,
        "superseded_by": None,
        "text": (
            "Claims must be reported within 30 days of the date of loss. "
            "You will need your policy number, date of loss, and photographs of the damage. "
            "A claims adjuster is assigned within 3 business days."
        ),
        "conditions": (
            "A claim submitted without photographs is held for inspection before "
            "an adjuster is assigned."
        ),
        "keywords": ["file", "claim", "report", "adjuster", "days", "submit"],
    },
    {
        "id": "POL-STATUS",
        "title": "Checking Claim Status",
        "effective": "2026-01-01",
        "expires": None,
        "superseded_by": None,
        "text": (
            "Claim status can be checked in the member portal. Statuses are: "
            "Received, Under Review, Adjuster Assigned, Approved, Denied, Paid. "
            "Payment is issued within 10 business days of approval."
        ),
        "conditions": None,
        "keywords": ["status", "claim", "portal", "approved", "paid", "review"],
    },
    {
        "id": "POL-APPEAL",
        "title": "Appealing a Denied Claim",
        "effective": "2026-01-01",
        "expires": None,
        "superseded_by": None,
        "text": (
            "A denied claim may be appealed within 60 days of the denial letter. "
            "Appeals require a written statement and any supporting documentation. "
            "Appeals are reviewed by a different adjuster than the original decision."
        ),
        "conditions": (
            "An appeal received after the 60-day window is not reviewed, and the "
            "original decision stands."
        ),
        "keywords": ["appeal", "denied", "denial", "dispute", "review"],
    },
]

CORPUS_BY_ID = {d["id"]: d for d in CORPUS}


def is_out_of_date(doc, today=TODAY):
    """Index metadata says this document should not be served."""
    if doc.get("superseded_by"):
        return True
    return bool(doc.get("expires")) and doc["expires"] < today

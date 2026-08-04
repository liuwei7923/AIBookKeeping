# Dummy Transaction Data

The deterministic dummy data generator provides `SourceTransaction` records and
their successfully constructed `CanonicalTransaction` results for local UI
development. It does not call OpenAI, read user data, or require Faker.

## Python Interface

```python
from uuid import UUID

from scripts.dummy_data import generate_dummy_transactions

dataset = generate_dummy_transactions(
    user_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
    count=24,
    seed=42,
)
```

`generate_dummy_transactions` returns a validated `DummyTransactionDataset`
with two arrays:

| Field | Contents |
| --- | --- |
| `user_id` | UUID that owns the complete generated dataset. |
| `source_transactions` | Original transaction-level values before processing. |
| `canonical_transactions` | Processed records with identity and categorization state. |

The source array has the requested length. A source without enough identity to
produce a fingerprint has no canonical counterpart. Matching records use the
same embedded `SourceTransaction`. The dataset validates that every source
record, including each source embedded in a canonical record, carries the same
`user_id` as its top-level owner. Canonical records do not duplicate the source
owner. The same `count` and `seed` produce byte-equivalent model JSON. A
different seed changes transaction content. `count` must be positive.

## Command Line

```bash
python -m scripts.dummy_data \
  --user-id 550e8400-e29b-41d4-a716-446655440000 \
  --count 24 \
  --seed 42 \
  --output data/dummy_transactions.json
```

The command creates missing parent directories and writes one JSON object that
can be validated with `DummyTransactionDataset.model_validate_json(...)`.
`--user-id` is required and must be a UUID; the generator never falls back to
an implicit user.

Generate fixtures for a second user by changing both the owner and output path:

```bash
python -m scripts.dummy_data \
  --user-id 550e8400-e29b-41d4-a716-446655440001 \
  --count 24 \
  --seed 99 \
  --output data/second-user-dummy-transactions.json
```

## Manual Judgment States

The generator cycles through eight scenarios in a fixed order. Generate at
least eight records to include all states in one dataset.

| State | AI categorization | Trusted categorization | Identity |
| --- | --- | --- | --- |
| Unreviewed | None | None | Complete |
| AI suggestion | Suggested category | None | Complete |
| Proposed category | Proposed new category | None | Complete |
| Unresolved | No category | None | Complete |
| Accepted AI | Suggested category | Same category | Complete |
| Corrected AI | Suggested category | Different category | Complete |
| Manual only | None | Selected category | Complete |
| Incomplete input | None | None | Source retained; no canonical transaction |

The seed controls merchant, amount, direction, and date values. Scenario
placement is based on record position so UI state coverage remains predictable
for every seed.

## Intended Use

This dataset is fixture-quality development data for rendering lists, filters,
and review actions. It is not representative production data and should not be
used to evaluate categorization quality or model accuracy.

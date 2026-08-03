# Dummy Transaction Data

The deterministic dummy data generator provides paired `SourceTransaction` and
`CanonicalTransaction` records for local UI development. It does not call
OpenAI, read user data, or require Faker.

## Python Interface

```python
from scripts.dummy_data import generate_dummy_transactions

dataset = generate_dummy_transactions(count=24, seed=42)
```

`generate_dummy_transactions` returns a validated `DummyTransactionDataset`
with two arrays:

| Field | Contents |
| --- | --- |
| `source_transactions` | Original transaction-level values before processing. |
| `canonical_transactions` | Processed records with identity and categorization state. |

The arrays have the requested length and matching records use the same embedded
`SourceTransaction`. The same `count` and `seed` produce byte-equivalent model
JSON. A different seed changes transaction content. `count` must be positive.

## Command Line

```bash
python -m scripts.dummy_data \
  --count 24 \
  --seed 42 \
  --output data/dummy_transactions.json
```

The command creates missing parent directories and writes one JSON object that
can be validated with `DummyTransactionDataset.model_validate_json(...)`.

## Manual Judgment States

The generator cycles through eight scenarios in a fixed order. Generate at
least eight records to include all states in one dataset.

| State | AI categorization | Manual categorization | Identity |
| --- | --- | --- | --- |
| Unreviewed | None | None | Complete |
| AI suggestion | Suggested category | None | Complete |
| Proposed category | Proposed new category | None | Complete |
| Unresolved | No category | None | Complete |
| Accepted AI | Suggested category | Same category | Complete |
| Corrected AI | Suggested category | Different category | Complete |
| Manual only | None | Selected category | Complete |
| Incomplete input | None | None | Insufficient; no fingerprint |

The seed controls merchant, amount, direction, and date values. Scenario
placement is based on record position so UI state coverage remains predictable
for every seed.

## Intended Use

This dataset is fixture-quality development data for rendering lists, filters,
and review actions. It is not representative production data and should not be
used to evaluate categorization quality or model accuracy.

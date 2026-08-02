# Transaction Domain Contracts

This reference is for developers implementing transaction ingestion,
normalization, AI categorization, or manual review. The validated models live in
`bookkeeping_app/domain_contracts.py` and do not depend on FastAPI or OpenAI SDK
types.

## Lifecycle

```text
SourceTransaction
        |
        | normalization and identity processing
        v
CanonicalTransaction
        |-- ai_categorization: CategorizationDecision | None
        `-- manual_categorization: ManualCategorization | None
```

`SourceTransaction` and `CanonicalTransaction` are separate models. If
processing fails, the source transaction remains available without constructing
a canonical transaction.

## Source Transaction

`SourceTransaction` preserves transaction-level values received from a source
before merchant and statement normalization. It is not the raw CSV row or image
content.

| Field | Meaning |
| --- | --- |
| `transaction_id` | Non-blank identifier assigned to the source transaction. |
| `date` | Date value supplied by the source, if present. |
| `merchant` | Merchant text supplied by the source, if present. |
| `statement` | Statement or description supplied by the source, if present. |
| `amount` | Parsed numeric amount, if available. |
| `original_category` | Category supplied by the source, if present. |

Source values are preserved; normalization belongs to canonical processing.

## Canonical Transaction

`CanonicalTransaction` embeds its `SourceTransaction` and adds processed
identity plus the latest AI and manual categorization state.

| Field | Meaning |
| --- | --- |
| `source` | The source transaction from which this record was produced. |
| `normalized_merchant` | Merchant identity produced by normalization. |
| `normalized_statement` | Statement identity produced by normalization. |
| `direction` | `debit`, `credit`, or `unknown`. |
| `identity_quality` | `complete`, `partial`, or `insufficient`. |
| `fingerprint` | Optional stable identity used for duplicate detection. |
| `ai_categorization` | Optional AI decision details. |
| `manual_categorization` | Optional trusted category selected by the user. |

The AI and manual categorizations may coexist. Manual review does not overwrite
the AI decision, allowing later comparison between the suggestion and the
category selected by the user.

## AI Categorization Decision

`CategorizationDecision` records one AI outcome and its explanation. All AI
decisions require review by domain definition, so the model does not carry a
redundant `needs_review` flag or an undefined confidence label.

| Decision type | Category fields |
| --- | --- |
| `ai_suggestion` | Requires `suggested_category`; forbids `proposed_category`. |
| `ai_proposed_new_category` | Requires `proposed_category`; forbids `suggested_category`. |
| `unresolved` | Forbids both category fields. |

Each decision has a non-blank `decision_id` and `reason`. It may cite
`supporting_memory_ids` when the AI used categorization memory.

An AI decision never becomes trusted automatically. If the user accepts the AI
suggestion, the application records the same category in
`manual_categorization`.

## Manual Categorization

`ManualCategorization` contains a non-blank category explicitly selected by the
user and an optional note. Its presence means manual review has occurred; its
absence means the transaction has not received a manual judgment.

## Deferred Contracts

Deterministic categorization types, confidence calculation,
`RecategorizationBatch`, and batch summary counts are intentionally deferred.

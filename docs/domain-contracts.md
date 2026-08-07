# Domain Contracts

This reference is for developers implementing users, transaction ingestion,
normalization, AI categorization, or manual review. The validated models live
in `bookkeeping_app/domain_contracts.py` and do not depend on FastAPI or OpenAI
SDK types.

## User

`User` represents a person inside the bookkeeping application. The application
generates a UUIDv4 when `user_id` is omitted. An existing UUID may be supplied
when restoring a user. `display_name` is optional, trimmed when provided, and
must not be blank.

Authentication identities, email addresses, credentials, status, and
persistence are intentionally deferred until their workflows are defined.

## Lifecycle

```text
SourceTransaction
        |
        | normalization and identity processing
        v
CanonicalTransaction
        |-- ai_categorization: AICategorization | None
        `-- trusted_categorization: TrustedCategorization | None
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
| `user_id` | Required UUID of the user who owns the transaction. |
| `transaction_id` | Globally unique UUID that remains stable for the transaction lifetime. |
| `date` | Date value supplied by the source, if present. |
| `merchant` | Merchant text supplied by the source, if present. |
| `statement` | Statement or description supplied by the source, if present. |
| `amount` | Exact decimal amount, if available. |
| `original_category` | Category supplied by the source, if present. |

Source values are preserved; normalization belongs to canonical processing.
Amounts use `Decimal` so financial values are not rounded through binary
floating-point conversion.

## Canonical Transaction

`CanonicalTransaction` embeds its `SourceTransaction` and adds processed
identity plus the latest AI and manual categorization state.

| Field | Meaning |
| --- | --- |
| `source` | The source transaction from which this record was produced. |
| `normalized_merchant` | Merchant identity produced by normalization. |
| `normalized_statement` | Statement identity produced by normalization. |
| `direction` | `debit` or `credit`; an amount is required before canonicalization. |
| `identity_quality` | `complete` or `partial`. |
| `fingerprint` | Required stable identity used for duplicate detection. |
| `ai_categorization` | Optional AI decision details. |
| `trusted_categorization` | Optional trusted category and the source of that trust. |

The AI and trusted categorizations may coexist. A trusted categorization does
not overwrite the AI decision, allowing later comparison between the suggestion
and the category accepted by the application.

User IDs are UUIDs assigned to a `User`. `CanonicalTransaction`,
`AICategorization`, and `TrustedCategorization` inherit ownership from the
embedded source transaction rather than duplicating `user_id`.

If the source identity is insufficient to generate a meaningful fingerprint,
the Source Transaction remains available but no Canonical Transaction is
constructed.

## AI Categorization

`AICategorization` records one AI outcome and its explanation. All AI
decisions require review by domain definition, so the model does not carry a
redundant `needs_review` flag or an undefined confidence label.

| Categorization type | Category field |
| --- | --- |
| `suggested` | Requires `category`; the value belongs to the known category set. |
| `proposed` | Requires `category`; the value is a newly proposed category name. |
| `not_available` | Requires `category` to be null. |

Each decision has a non-blank `decision_id` and `reason`. It may cite
`supporting_memory_ids` when the AI used categorization memory.

An AI decision never becomes trusted automatically. If the user accepts the AI
suggestion, the application records the same category in
`trusted_categorization` with source `confirmed_ai_suggestion`.

## Trusted Categorization

`TrustedCategorization` contains a non-blank category, an optional note, and the
source through which trust was established: manual classification, a confirmed
AI suggestion, or a corrected AI suggestion. Bank-statement categories remain
untrusted until user review. Its presence makes the Canonical Transaction
eligible for Categorization Memory.

## Deferred Contracts

Deterministic categorization types, confidence calculation,
`RecategorizationBatch`, and batch summary counts are intentionally deferred.

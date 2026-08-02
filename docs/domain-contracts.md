# Phase 1 Domain Contracts

This reference is for developers implementing Transaction Ingestion,
Categorization Memory, the OpenAI Reviewer, or the Recategorization Engine. The
validated models live in `bookkeeping_app/domain_contracts.py` and do not import
FastAPI upload types or OpenAI SDK response types.

## Canonical Transaction

`CanonicalTransaction` preserves source data while carrying the normalized
identity used by categorization.

| Field | Meaning |
| --- | --- |
| `transaction_id` | Non-blank identifier unique within one request. |
| `date` | Original transaction date text, if provided. |
| `merchant` | Original merchant text, if provided. |
| `statement` | Original statement or description text, if provided. |
| `amount` | Original numeric amount, if parseable. |
| `original_category` | Category supplied by the source, if any. |
| `normalized_merchant` | Merchant identity normalized by ingestion. |
| `normalized_statement` | Statement identity normalized by ingestion. |
| `direction` | `debit`, `credit`, or `unknown`. |
| `identity_quality` | `complete`, `partial`, or `insufficient`. |
| `fingerprint` | Optional stable identity for duplicate detection. |

Source fields may be absent because incomplete input is a valid domain state.
Ingestion decides normalization, direction, identity quality, and fingerprinting;
the contract only validates and transports those results.

## Categorization Decision

`CategorizationDecision` associates one transaction ID with exactly one Phase 1
decision path.

| Decision type | Category field | Review requirement |
| --- | --- | --- |
| `exact_statement_memory_match` | `accepted_category` | Must not need review. |
| `merchant_consensus` | `accepted_category` | Must not need review. |
| `ai_suggestion_with_relevant_memory` | `suggested_category` | Must need review. |
| `ai_suggestion_without_relevant_memory` | `suggested_category` | Must need review. |
| `ai_proposed_new_category` | `proposed_category` | Must need review. |
| `unresolved` | No category | Must need review. |

Every decision also carries `confidence`, a human-readable `reason`, and the IDs
of supporting memory items when applicable. Accepted, suggested, and proposed
categories are separate fields so downstream code cannot silently promote an AI
result into an accepted category.

The `with_relevant_memory` path requires at least one supporting memory ID; the
`without_relevant_memory` path rejects supporting memory IDs. This keeps the two
AI paths distinguishable from their data, not only from their type names.

An AI-derived result is never a Trusted Categorization in Phase 1. It becomes
trusted only after explicit user confirmation, which is outside these contracts.

## Recategorization Batch

`RecategorizationResult` binds a canonical transaction to its decision and its
zero-based input position. Their transaction IDs must match.

`RecategorizationBatch` contains the ordered results, batch status, and OpenAI
request count. Result positions must be contiguous and in input order. The model
derives these response fields from its results:

- `total_count`
- `deterministic_count`
- `ai_reviewed_count`
- `unknown_count`
- `needs_review_count`
- `approval_required`

`approval_required` is true when status is `approval_required`; otherwise a
completed batch uses status `completed`. Computing summary fields prevents a
caller from constructing a batch whose counts disagree with its decisions.

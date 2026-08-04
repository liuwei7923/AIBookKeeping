# Memory Store Design and Implementation Plan

## Context

The application currently persists categorization memory as a JSON array of
`CategorizationMemoryItem` objects. That persistence model duplicates most of
`CanonicalTransaction` while using incompatible field types and vocabulary:

- memory amounts use `float`; domain amounts use `Decimal`
- legacy memory directions used `income` and `expense`; all transaction models
  now use `credit` and `debit`
- memory records lack user ownership and canonical transaction identity
- legacy canonical fingerprints were optional; the domain contract now requires
  every canonical transaction to have one

The agreed domain direction is that Categorization Memory is not a second kind
of transaction. It is the collection of Canonical Transactions whose
categorization is trusted.

## Goals

- Use `CanonicalTransaction` as the only normalized transaction model.
- Represent imported and user-confirmed categories uniformly as trusted
  categorizations.
- Require every Canonical Transaction to have a deterministic fingerprint.
- Introduce a small `MemoryStore` interface that supports file-backed,
  database-backed, and in-memory adapters.
- Enforce user isolation, trust, duplicate detection, and conflict handling at
  the Memory Store seam.
- Keep retrieval ranking and categorization decisions outside persistence.
- Preserve AI suggestions independently from trusted categorizations for later
  review and audit.

## Non-goals

- Selecting a database or ORM.
- Adding a persistent review queue.
- Designing deletion, history revision, or rollback workflows.
- Automatically trusting AI suggestions.
- Adding generic CRUD methods to the Memory Store.
- Implementing category-reference validation.

## Constraints and assumptions

- Storage remains file-backed during Phase 1.
- A database-backed adapter must be possible without changing callers.
- All financial records are user-owned and all queries are user-scoped.
- Fingerprints detect duplicate transactions; they are not record identifiers.
- A Canonical Transaction is constructed only when a meaningful deterministic
  fingerprint can be generated.
- A Source Transaction whose identity is insufficient remains available as an
  ingestion failure or incomplete input; it does not become a Canonical
  Transaction.
- The checked-in memory file is currently empty, so no production data migration
  is needed in the repository. Migration behavior must still fail safely for
  non-empty legacy files.

## Proposed domain model

### Trusted categorization

The narrow `ManualCategorization` model is replaced by a trusted categorization
that records how trust was established.

```python
class TrustedCategorizationSource(StrEnum):
    IMPORTED_HISTORY = "imported_history"
    MANUAL_CLASSIFICATION = "manual_classification"
    CONFIRMED_AI_SUGGESTION = "confirmed_ai_suggestion"
    CORRECTED_AI_SUGGESTION = "corrected_ai_suggestion"


class TrustedCategorization(BaseModel):
    category: str
    source: TrustedCategorizationSource
    note: str | None = None
```

`CanonicalTransaction` retains AI and trusted categorization independently:

```python
class CanonicalTransaction(BaseModel):
    source: SourceTransaction
    normalized_merchant: str | None = None
    normalized_statement: str | None = None
    direction: TransactionDirection
    identity_quality: TransactionIdentityQuality
    fingerprint: str = Field(min_length=1)
    ai_categorization: CategorizationDecision | None = None
    trusted_categorization: TrustedCategorization | None = None
```

A transaction with only `ai_categorization` is not trusted and cannot be stored
as categorization memory. AI and trusted categorizations may coexist so the
application can later compare a suggestion with the user's final decision.

### Transaction identity

`transaction_id` is a globally unique UUID that remains stable for the
life of the imported transaction. It identifies a record. The fingerprint is a
deterministic value derived from normalized transaction facts and detects
equivalent transactions across repeated imports.

A fingerprint requires:

- `user_id`
- normalized date
- normalized amount
- at least one of normalized merchant or normalized statement

The exact fingerprint serialization must be versioned or otherwise kept stable.
Missing identity fields must produce an explicit ingestion result instead of a
random, request-derived, or nullable fingerprint.

## Memory Store interface

```python
class MemoryStore(Protocol):
    def record_trusted(
        self,
        commands: Sequence[RecordTrustedCommand],
    ) -> MemoryWriteResult:
        """Atomically record trusted canonical transactions."""

    def find_relevant(
        self,
        query: MemoryQuery,
    ) -> tuple[CanonicalTransaction, ...]:
        """Find trusted transactions for one user, merchant, and direction."""

    def list_for_user(
        self,
        query: MemoryListQuery,
    ) -> MemoryPage:
        """List one user's trusted transactions with cursor pagination."""
```

### Recording trusted transactions

Conflict behavior belongs to the write command, not to Canonical Transaction:

```python
class FingerprintConflictPolicy(StrEnum):
    REJECT = "reject"
    REPLACE_TRUSTED_CATEGORY = "replace_trusted_category"


class RecordTrustedCommand(BaseModel):
    transaction: CanonicalTransaction
    conflict_policy: FingerprintConflictPolicy = FingerprintConflictPolicy.REJECT
    override_reason: str | None = None
```

The default is always `REJECT`. `REPLACE_TRUSTED_CATEGORY` requires an explicit
user-authorized workflow and a non-blank reason. AI output cannot request an
override.

Per-item outcomes are:

```python
class MemoryWriteStatus(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    REPLACED = "replaced"
    REJECTED = "rejected"
```

Write rules:

| Condition | Outcome |
| --- | --- |
| New user-scoped fingerprint | `CREATED` |
| Same user, fingerprint, and trusted category | `DUPLICATE` |
| Same user and fingerprint, different category, default policy | `CONFLICT` |
| Same conflict with an authorized replacement policy and reason | `REPLACED` |
| Missing trusted categorization or invalid ownership | `REJECTED` |

The batch is committed atomically. The result reports each command's outcome;
expected duplicates and conflicts do not become infrastructure exceptions.

### Finding relevant memory

```python
class MemoryQuery(BaseModel):
    user_id: UserId
    normalized_merchant: str
    direction: TransactionDirection
```

`find_relevant` performs only persistence-efficient filtering:

- same user
- same normalized merchant
- compatible direction
- trusted categorization present

It does not rank candidates, calculate consensus, assign confidence, or choose a
category. A shared retrieval module performs fingerprint deduplication, exact
statement matching, ranking, aggregate category counts, and example limiting so
all storage adapters produce the same categorization behavior.

### Listing memory

```python
class MemoryListQuery(BaseModel):
    user_id: UserId
    limit: int = Field(default=100, ge=1, le=500)
    cursor: str | None = None


class MemoryPage(BaseModel):
    transactions: tuple[CanonicalTransaction, ...]
    next_cursor: str | None = None
```

The cursor is opaque to callers. No interface method exposes file offsets,
database primary keys, or full fingerprint sets.

## Data flow

```text
CSV row
  -> SourceTransaction
  -> canonical ingestion and fingerprinting
  -> CanonicalTransaction
  -> trusted import or explicit user decision
  -> CanonicalTransaction.trusted_categorization
  -> MemoryStore.record_trusted

New CanonicalTransaction
  -> MemoryStore.find_relevant
  -> shared Memory Retrieval
  -> deterministic rules or bounded AI review
  -> CategorizationDecision
```

## Adapters

### FileMemoryStore

- Stores complete Canonical Transactions as JSON.
- Uses a temporary file and atomic replacement for writes.
- Serializes `Decimal`, UUID, and enums through Pydantic JSON mode.
- Enforces user-scoped duplicate and conflict rules.
- Must not silently accept the legacy flat memory schema.

### DatabaseMemoryStore

- Implements the same interface with transactions and indexed queries.
- Uses a uniqueness constraint compatible with `(user_id, fingerprint)`.
- Does not require callers to join transaction and memory tables.
- Its physical schema may be one table or several; that decision is hidden by
  the adapter.

### InMemoryMemoryStore

- Supports fast contract tests and engine tests.
- Implements production semantics rather than bypassing validation.

## Alternatives considered

### Separate flat `CategorizationMemoryItem`

Rejected because it duplicates Canonical Transaction fields and has already
drifted in amount type, direction vocabulary, ownership, and identity behavior.

### Memory record wrapping a separate transaction table

Not required for Phase 1. It introduces an apparent join requirement without a
current need for independent memory-record lifecycle. A future database adapter
may normalize its physical schema internally without changing the interface.

### Generic repository CRUD

Rejected because `save`, `update`, `delete`, `find_by_user`, and
`get_fingerprint_set` expose implementation details or leave trust and conflict
semantics to callers.

### Boolean `is_forced`

Rejected in favor of an explicit conflict policy. A boolean does not state what
is being forced and cannot grow safely when more conflict actions are added.

## Rollout and implementation plan

### Step 0: Align specifications

- Update Phase 1 issues #18 and #19 before implementation.
- Replace optional-fingerprint requirements with the non-null invariant.
- State that insufficient Source Transactions do not become Canonical
  Transactions.
- Remove the requirement for a separate categorization-memory record model.
- Document the conflict policy and trusted-only Memory Store rule.

Exit criteria: README, domain contracts documentation, and issue acceptance
criteria no longer contradict the design.

### Step 1: Evolve domain contracts

- Add `TrustedCategorizationSource` and `TrustedCategorization`. (Complete)
- Replace `manual_categorization` with `trusted_categorization`. (Complete)
- Make `fingerprint` required on Canonical Transaction. (Complete)
- Make transaction IDs globally unique and stable. (Complete)
- Remove `INSUFFICIENT` from `TransactionIdentityQuality`; insufficient sources
  do not produce Canonical Transactions. (Complete)
- Update domain and dummy-data tests.

Exit criteria: invalid Canonical Transactions cannot be constructed, imported
history and manual confirmation use one trusted model, and all model tests pass.

### Step 2: Implement canonical ingestion

- Normalize supported CSV aliases into Source Transactions.
- Normalize merchant, statement, date, amount, and direction.
- Generate deterministic fingerprints from the agreed minimum identity fields.
- Return explicit incomplete-ingestion results for insufficient sources.
- Preserve input ordering and stable transaction IDs.

Exit criteria: the revised acceptance coverage for #18 passes.

### Step 3: Define the Memory Store seam test-first

- Add the protocol, query, command, page, and result contracts.
- Write reusable Memory Store contract tests.
- Implement `InMemoryMemoryStore` as the first adapter.
- Cover user isolation, atomic batches, duplicates, conflicts, authorized
  replacement, pagination, and relevant lookup.

Exit criteria: all observable Memory Store behavior is captured through its
public interface.

### Step 4: Implement FileMemoryStore

- Replace flat `CategorizationMemoryItem` persistence with Canonical
  Transaction persistence.
- Use atomic file replacement and safe decoding.
- Add an explicit empty/legacy schema check.
- Move CSV parsing and canonicalization outside the adapter.
- Update the memory HTTP routes to receive the store through dependency
  injection rather than mutating a module-level path.

Exit criteria: the same contract suite passes against in-memory and file-backed
adapters, and existing live HTTP tests pass with a temporary file.

### Step 5: Add shared memory retrieval

- Build deterministic deduplication and ranking over `find_relevant` results.
- Preserve conflicting categories.
- Compute aggregate counts from all distinct relevant transactions.
- Limit only the detailed examples supplied to AI.
- Update decisions to reference supporting transaction IDs, or explicitly
  retain a storage-owned evidence identifier if transaction IDs are not made
  persistent.

Exit criteria: revised #19 tests cover exact, duplicate, conflicting,
user-isolated, and absent evidence.

### Step 6: Integrate the Recategorization Engine

- Inject MemoryStore and the shared retrieval module into the engine.
- Resolve strong deterministic matches before OpenAI.
- Send only unresolved transactions to the bounded reviewer.
- Preserve output order and decision provenance.

Exit criteria: Phase 1 engine and public endpoint acceptance tests pass without
live OpenAI calls.

### Step 7: Prove database compatibility

- Run the Memory Store contract suite against a minimal database adapter or a
  throwaway relational prototype.
- Verify uniqueness, transaction atomicity, cursor behavior, and relevant-query
  indexing.
- Do not ship a database dependency until the product needs it.

Exit criteria: no interface change is required to support the second adapter.

## Testing and observability

Contract tests must run unchanged against every adapter. Application tests
should replace the adapter at the Memory Store seam rather than patch global
file paths.

Required cases:

- reject an untrusted Canonical Transaction
- isolate two users in one shared store
- create a new trusted transaction
- identify idempotent duplicate imports
- surface category conflicts without overwriting
- replace only with explicit policy and reason
- roll back an atomic batch after infrastructure failure
- retrieve only matching merchant and direction
- paginate without omissions or duplicates
- reject corrupt or legacy file payloads explicitly

Log batch-level counts without logging merchants, statements, amounts, notes,
or categories. Useful fields include operation, user ID, created count,
duplicate count, conflict count, rejected count, and elapsed time.

## Risks

- The change from request-scoped transaction IDs to persistent IDs affects the
  Phase 1 issue contract and downstream integrations.
- The minimum fingerprint fields may reject transaction sources the current CSV
  parser accepts.
- Replacing manual categorization terminology affects dummy fixtures and future
  UI assumptions.
- Atomic file replacement is not sufficient for multiple writer processes
  unless file locking or a single-writer constraint is added.
- `REPLACE_TRUSTED_CATEGORY` can destroy audit history unless the adapter keeps a
  revision log or replacement provenance.
- Cursor semantics can drift across adapters unless contract tests define stable
  traversal behavior.

## Open questions

1. Should the fingerprint include normalized statement when merchant is already
   present, or use statement only as a fallback? This changes duplicate identity.
2. Are date, amount, and merchant-or-statement the final minimum fields required
   to construct a Canonical Transaction?
3. Should authorized category replacement mutate the existing transaction or
   append a revision while marking the old categorization inactive?
4. Should `supporting_memory_ids` be renamed to
   `supporting_transaction_ids` after transaction IDs become persistent?
5. Should the Phase 1 FileMemoryStore support multiple writer processes, or is a
   documented single-writer constraint sufficient?

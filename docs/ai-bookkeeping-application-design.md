# AI Bookkeeping Application Design

## Context

The current product in [`app/README.md`](/Users/w_liu/FiniancialMind/app/README.md) is a CSV-first FastAPI backend for bank-statement transaction intake, categorization-memory retrieval, and AI-assisted recategorization. The existing implementation already has:

- file-backed categorization memory retrieval
- CSV parsing
- image-based transaction extraction
- OpenAI-backed category review

The main gap is that the product goal and the current implementation are not fully aligned yet. The product direction says categorization should be memory-first and cost-aware, but the current recategorization flow in [`bookkeeping_app/openai_service.py`](/Users/w_liu/FiniancialMind/app/bookkeeping_app/openai_service.py) does not yet retrieve relevant local memory before calling the model.

This document proposes a practical design for evolving the MVP into an AI bookkeeping application that is useful for individuals or small businesses without introducing unnecessary infrastructure too early.

## Goals

- Turn raw financial inputs into normalized, reviewable bookkeeping transactions.
- Make categorization memory the primary decision engine for repeated merchants and recurring patterns.
- Use AI selectively for low-confidence or ambiguous transactions.
- Keep operating costs and system complexity low in the MVP stage.
- Preserve human review and auditability for every category suggestion.
- Support gradual expansion from CSV-first workflows to richer bookkeeping workflows.

## Non-goals

- Full double-entry accounting for v1.
- General ledger, invoicing, payroll, or tax filing automation.
- Autonomous posting into external accounting systems without review.
- Fine-tuning custom models.
- Multi-tenant SaaS infrastructure in the first phase.

## Constraints And Assumptions

- The current backend is FastAPI-based and file-backed, and that should remain true until there is clear pressure to add a database.
- The primary early users are individuals or small teams managing financial records through distinct user accounts and explicit data boundaries.
- Input sources will be inconsistent across banks, cards, and exports.
- Bank-provided labels and AI suggestions are not trusted; memory is created
  only from an explicit user decision.
- High-confidence repeated merchant matches should avoid model calls whenever possible.
- The user must be able to see why a category was suggested.

## User Problems

Users trying to keep books from statements and exports usually face the same problems:

- merchant names are inconsistent across banks
- categories drift over time
- manual review is repetitive
- bookkeeping software is rigid or expensive
- AI-only categorization is difficult to trust without history and explanations

The application should solve those by combining deterministic memory, normalization, and limited AI reasoning.

## Proposed Product Shape

The application should be built around a three-stage loop:

1. Ingest transactions from CSVs or statement images.
2. Categorize transactions using a memory-first pipeline with AI fallback.
3. Review, correct, and optionally promote approved decisions back into memory.

This creates a compounding system: every approved correction improves future categorization quality.

## Primary Workflows

### 1. Initial Transaction Review

The user uploads transactions from a bank statement and reviews them.

System behavior:

- parse rows into canonical transaction fields
- normalize merchants and amounts
- deduplicate obvious duplicate transactions
- present imported or suggested categories for review
- record only the user's confirmed category as trusted memory

Output:

- reviewed and unresolved transactions
- duplicate count
- warnings for malformed rows

### 2. New Transaction Intake

The user uploads a new CSV or image-derived transaction set.

System behavior:

- parse and normalize input
- assign each row a stable transaction fingerprint
- run categorization pipeline
- return suggested category, confidence, and explanation

Output:

- categorized transactions
- unresolved transactions
- warnings for missing merchant or malformed amount values

### 3. Review And Approval

The user reviews suggested categories before accepting them.

System behavior:

- surface exact-match and rule-match decisions separately from AI-assisted decisions
- allow manual category overrides
- optionally save approved overrides into categorization memory

Output:

- approved transactions
- overridden transactions
- newly created memory entries

## Architecture Overview

### Core components

1. Ingestion layer
   Handles CSV parsing, image extraction, input normalization, and validation.

2. Memory engine
   Stores historical categorized examples and retrieves relevant examples for a new transaction.

3. Categorization engine
   Applies deterministic matching, rule-based heuristics, and AI fallback.

4. Review layer
   Produces explanations, confidence signals, and approval-ready outputs.

5. Storage layer
   Persists memory, category reference data, decision logs, and review outputs.

### Recommended near-term module split

The current codebase can evolve into these responsibilities:

- `parsers.py`
  Keep for input parsing and canonical transaction shape extraction.
- `memory.py`
  Keep for storage and import, but extend with retrieval and dedup helpers.
- `memory_retrieval.py`
  New module for candidate lookup and ranking.
- `categorization.py`
  New module for the memory-first decision pipeline.
- `category_reference.py`
  New module for canonical category definitions, aliases, and policy.
- `review.py`
  New module for approval output formatting and review-state handling.
- `openai_service.py`
  Narrow to model-only responsibilities, not orchestration.

## Data Model And Interfaces

### Canonical transaction

Each parsed transaction should move through the system in a canonical form:

- `transaction_id`
- `date`
- `merchant_raw`
- `merchant_normalized`
- `statement`
- `amount`
- `direction`
- `currency`
- `account_name`
- `source_type`
- `source_file`
- `original_category`

### Categorization memory item

The current schema is close, but it should grow to include:

- `memory_id`
- `merchant`
- `normalized_merchant`
- `statement`
- `amount`
- `direction`
- `corrected_category`
- `original_category`
- `source`
- `trust_level`
- `created_at`
- `last_used_at`
- `usage_count`
- `notes`

Why:

- `trust_level` distinguishes imported history from manually approved overrides and AI-generated suggestions
- `usage_count` and `last_used_at` support maintenance and ranking
- provenance fields make the system auditable

### Category reference

Add a dedicated file-backed category reference model with:

- canonical category name
- description
- aliases
- positive merchant examples
- negative examples if needed
- bookkeeping notes

This prevents category drift and gives both deterministic logic and model prompts a stable vocabulary.

## Categorization Pipeline

This is the core design decision.

### Step 1. Normalize

For each transaction:

- sanitize merchant text
- derive normalized merchant
- preserve raw merchant and statement text
- infer direction from amount
- validate candidate category vocabulary

### Step 2. Deterministic retrieval

Search memory in order of decreasing precision:

1. exact normalized merchant match
2. strong statement pattern match
3. merchant alias match from category reference
4. merchant plus direction match
5. merchant plus amount-band match for recurring patterns

If a strong, unambiguous match is found, return a suggestion without calling AI.

### Step 3. Candidate ranking

If multiple memory items match, rank by:

- normalized merchant equality
- same direction
- recent usage
- trust level
- frequency of same category among matching examples
- amount proximity when useful

### Step 4. Confidence scoring

Produce a simple confidence model with labels such as:

- `high`
- `medium`
- `low`

Recommended logic:

- `high`
  deterministic exact match with consistent historical category
- `medium`
  strong candidate set but minor ambiguity
- `low`
  weak retrieval or conflicting history

### Step 5. AI fallback

Only call OpenAI when:

- there is no high-confidence deterministic answer
- the candidate set is conflicting
- the merchant is new or poorly normalized

Prompt inputs should include:

- canonical transaction fields
- top ranked memory examples only
- category reference shortlist
- explicit instruction to choose from canonical categories only

### Step 6. Human review

Every result should return:

- `suggested_category`
- `decision_type`
- `confidence`
- `reason`
- `supporting_examples`

That keeps the system explainable and suitable for review.

## Decision Types

Add an explicit decision taxonomy:

- `exact_memory_match`
- `pattern_match`
- `category_reference_rule`
- `ai_with_memory_context`
- `ai_without_memory_context`
- `manual_override`
- `unresolved`

This will be more useful than a single freeform reason string and will help analytics later.

## API Evolution

The current API should evolve without breaking the MVP path.

### Keep

- `GET /health`
- `GET /categorization-memory`
- `POST /transactions`

### Extend

#### `POST /transactions`

Response should grow to include:

- `transaction_id`
- `suggested_category`
- `confidence`
- `decision_type`
- `reason`
- `supporting_examples`
- `needs_review`

#### New review-confirmation endpoint

Purpose:

- call `MemoryStore.record_trusted()` for user-approved categories

Input:

- reviewed canonical transactions
- optional notes
- trust level

#### New `GET /category-reference`

Purpose:

- return canonical categories and aliases

#### New `POST /category-reference/import`

Purpose:

- upload or replace category vocabulary and alias definitions

#### New `GET /review-queue`

Purpose:

- list transactions that remain unresolved or low-confidence

## Storage Design

Stay file-backed for now, but split files by responsibility instead of overloading one memory file.

Recommended storage:

- `data/categorization_memory.json`
- `data/category_reference.json`
- `data/review_queue.json`
- `data/decision_log.jsonl`

Why:

- `categorization_memory.json`
  user-confirmed categories and approved corrections
- `category_reference.json`
  vocabulary control and category policy
- `review_queue.json`
  unresolved transactions awaiting human action
- `decision_log.jsonl`
  append-only operational trace for debugging and prompt evaluation

## Security And Privacy

Because this is financial data, default privacy should be conservative.

Recommended controls:

- keep memory local by default
- avoid sending entire historical datasets to the model
- send only top-ranked examples
- redact unnecessary identifying fields before model calls
- log model usage counts and categories, but not raw sensitive payloads unless explicitly enabled
- document retention expectations clearly

## Observability

The app already has usage metrics. It should expand into categorization quality metrics:

- total transactions processed
- percent resolved without AI
- percent resolved with AI
- low-confidence rate
- override rate
- unresolved rate
- per-category disagreement rate
- model calls per batch

These metrics matter because the product should get cheaper and more accurate over time.

## Testing Strategy

The design should be testable at three layers.

### Unit tests

- merchant normalization
- memory deduplication
- candidate ranking
- confidence scoring
- category-reference validation

### API tests

- import behavior
- recategorization responses with deterministic matches
- recategorization responses with AI fallback
- promotion of approved corrections into memory

### Golden tests

Maintain a set of representative CSV fixtures and expected categorizations to track regressions over time.

This is especially important once prompt or retrieval logic changes.

## Rollout Plan

### Phase 1. Complete memory-first categorization

- add retrieval and ranking
- enrich recategorization response with confidence and decision type
- call OpenAI only for low-confidence cases

### Phase 2. Add category reference control

- define canonical categories
- add alias support
- restrict model outputs to known categories

### Phase 3. Add review and promotion loop

- store approved overrides
- introduce review queue and promotion endpoint
- track disagreement metrics

### Phase 4. Expand input sources

- improve image extraction flow
- support bank-specific CSV mapping profiles if needed
- add better merchant normalization patterns

### Phase 5. Consider external integrations

Only after the review loop is stable:

- export to accounting systems
- sync with bookkeeping platforms
- support richer bookkeeping workflows

## Alternatives Considered

### Alternative A. AI-first categorization

Description:

- send every transaction to the model and use memory only as optional prompt context

Why not recommended:

- higher cost
- weaker consistency
- worse explainability
- does not take advantage of repeated merchant patterns

### Alternative B. Rule-only engine

Description:

- avoid model usage and rely only on exact matches and static rules

Why not recommended:

- brittle for unseen merchants
- poor generalization
- hard to maintain once sources diversify

### Alternative C. Full database and workflow system now

Description:

- introduce Postgres, user accounts, review state tables, and asynchronous jobs immediately

Why not recommended:

- too much complexity for current scope
- current design principles prefer local file-backed storage first

## Recommended Approach

Choose a memory-first hybrid architecture:

- deterministic memory for repeated patterns
- category-reference controls for consistency
- AI fallback for ambiguity
- human approval for trust and compounding improvement

This best matches the current repo direction, the cost-control strategy in the README, and the project's explicit preference for simple local infrastructure first.

## Risks

- merchant normalization may be too weak for noisy bank data
- imported history may contain inconsistent categories
- users may over-trust AI output if confidence language is unclear
- file-backed storage may become awkward once review state becomes more complex
- prompt drift may change results unless golden tests are maintained

## Open Questions

- Should the product support multiple ledgers or profiles for different businesses?
- How should transfer, refund, and reversal transactions be represented?
- Do users want category suggestions only, or bookkeeping-ready export formats too?
- When should approved overrides become trusted memory automatically, if ever?
- Is a lightweight desktop UI eventually needed, or is API plus scripts enough for the target user?

## Immediate Next Steps

1. Implement `memory_retrieval.py` and a deterministic candidate ranking path.
2. Update `/recategorize-transactions-csv` to run memory-first before model fallback.
3. Add `decision_type`, `confidence`, and `supporting_examples` to the response shape.
4. Introduce `category_reference.json` and restrict outputs to canonical categories.
5. Add fixture-based tests that compare deterministic and AI-assisted categorization behavior.

# GitHub Issue Drafts

These are the issue drafts for the next phase of the AI bookkeeping app.
The current product direction is CSV-first categorization with local memory
from prior manual labels. The original image-to-JSON path is no longer the
main product focus.

## Issue 1: Redesign the app around CSV-first categorization memory

**Title**
Pivot product scope from image extraction to CSV-first categorization memory

**Body**
### Goal
Refocus the app around the actual product need:
- input is a transactions CSV
- historical manual labels act as categorization memory
- output is improved suggested categories for future transactions

### Why
The image extraction path was useful as a learning exercise, but it is not the
shortest path to the bookkeeping product we actually want to build. The real
value is in reusing prior manual categorization decisions.

### Scope
- Update README and roadmap language
- Treat CSV recategorization as the primary workflow
- De-emphasize image extraction in future planning

### Acceptance Criteria
- README describes the project as CSV-first
- Product roadmap is centered on memory-driven categorization
- Future development uses CSV as the main input format

## Issue 2: Design categorization memory schema and local storage

**Title**
Design and implement local categorization memory schema

**Body**
### Goal
Define how manual categorization history will be stored so it can be reused for
future transaction labeling.

### Why
The app needs a trustworthy, inspectable memory source. We are not fine-tuning
the model yet. We are using retrieval plus prompt-time examples from local
human-approved history.

### Proposed storage
Use a local JSON file first:
- `data/categorization_memory.json`

Each memory item should represent a trusted labeled example, not just a raw
transaction.

### Proposed schema
```json
{
  "id": "uuid",
  "date": "2026-03-24",
  "merchant": "Electrify America",
  "normalized_merchant": "electrify america",
  "amount": -7.0,
  "direction": "expense",
  "original_category": "Gas",
  "corrected_category": "Electric Vehicle Charging",
  "source": "manual_override",
  "notes": "EV charging merchant",
  "created_at": "2026-03-28T10:15:00Z",
  "updated_at": "2026-03-28T10:15:00Z",
  "confidence": 1.0,
  "usage_count": 0,
  "last_matched_at": null
}
```

### Acceptance Criteria
- Schema is documented in code and README
- Memory can be loaded from local JSON
- Memory items preserve both original and corrected category

## Issue 3: Add API to import training dataset into categorization memory

**Title**
Add `POST /categorization-memory/import` for labeled history import

**Body**
### Goal
Allow importing a labeled CSV of historical transactions into the local memory
store.

### Input
CSV with fields such as:
- `date`
- `merchant`
- `amount`
- `original_category`
- `corrected_category`
- optional `notes`

### Output
Return import summary:
```json
{
  "imported": 120,
  "skipped": 3
}
```

### Notes
- Normalize merchants during import
- Infer direction from amount
- Reject invalid rows cleanly
- Store trusted imported examples as reusable memory

### Acceptance Criteria
- API accepts labeled CSV upload
- Rows are normalized and stored locally
- Import summary reports imported/skipped counts

## Issue 4: Add API to retrieve categorization memory in human-readable form

**Title**
Add `GET /categorization-memory` to inspect stored memory

**Body**
### Goal
Make the system’s memory visible and debuggable.

### Why
The user needs to inspect what the app has learned from prior manual labels.
This is critical for trust and debugging.

### API behavior
- Return stored memory items as JSON
- Prefer simple and human-readable output
- Later we can add filters such as:
  - `?merchant=amazon`
  - `?limit=50`

### Acceptance Criteria
- API returns current memory store
- Output is readable and stable
- Can be used to verify imported labeled history

## Issue 5: Use categorization memory to label future transactions

**Title**
Update `POST /recategorize-transactions-csv` to use relevant memory examples

**Body**
### Goal
Use prior manual labels as context when categorizing future transactions.

### Retrieval strategy
For each future transaction:
1. Normalize merchant
2. Search local memory
3. Rank relevant examples using:
   - exact normalized merchant match
   - fuzzy merchant similarity
   - same direction
   - same original category
   - optional amount similarity
4. Keep only top N examples
5. Send those examples to OpenAI as context

### Important
Do not send the full memory store to the model. This should be a retrieval
step, not a full dump of historical data.

### Acceptance Criteria
- Recategorization endpoint loads local memory
- Only a limited relevant subset is passed to the model
- Suggested categories reflect prior manual corrections when relevant

## Issue 6: Add token usage controls for memory-aware categorization

**Title**
Add token-budget controls to the recategorization workflow

**Body**
### Goal
Keep OpenAI cost low while still benefiting from prior manual labels.

### Proposed controls
- Send only fields needed for categorization
- Limit context examples to a small number, e.g. 5 to 20
- Batch future transactions into smaller requests
- Prefer rule-first behavior for exact trusted matches
- Skip the model when a high-confidence direct match exists

### Acceptance Criteria
- Prompt payload size is intentionally capped
- Exact trusted matches can bypass the LLM
- Context selection is predictable and cheap

## Issue 7: Add dedicated category reference file

**Title**
Add dedicated category reference file for definitions and patterns

**Body**
### Goal
Create a single source of truth for category names, definitions, and matching
patterns so categorization stays consistent over time.

### Why
Without a fixed category reference, the model will drift into overlapping or
inconsistent labels such as:
- `Transportation`
- `Auto & Transport`
- `Taxi & Ride Shares`
- `Rideshare`

### Proposed file
- `data/category_reference.json`

### Suggested structure
```json
[
  {
    "name": "Electric Vehicle Charging",
    "definition": "Charging-related expenses for electric vehicles.",
    "aliases": ["EV Charging"],
    "include_patterns": ["electrify america", "chargepoint", "evgo"],
    "exclude_patterns": ["gas station"],
    "example_merchants": ["Electrify America", "ChargePoint"]
  }
]
```

### How it will be used
- Validate allowed category names
- Give the model a stable category vocabulary
- Support future matching and merchant rules
- Improve consistency between memory and outputs

### Acceptance Criteria
- Category reference file exists
- It defines canonical category names and simple patterns
- Memory and AI outputs can be checked against it

## Issue 8: Add tests for memory import, retrieval, and memory-aware recategorization

**Title**
Add tests for categorization memory workflows

**Body**
### Goal
Protect the new memory-driven behavior with tests.

### Coverage
- import labeled CSV into memory
- retrieve memory output
- normalize merchants consistently
- select relevant memory examples
- cap prompt context size
- ensure memory is included in recategorization prompt

### Acceptance Criteria
- Tests cover import, retrieval, and recategorization flows
- Tests cover exact merchant match behavior
- Tests cover context-size limits

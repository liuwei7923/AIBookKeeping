# AI Bookkeeping App MVP

CSV-first FastAPI backend for improving transaction categories using your own historical labeling decisions.

## Product Goal

The app is built around one core idea:

1. import your historically labeled transactions
2. store them as local categorization memory
3. use that memory to help label future transaction CSVs

This is not a fine-tuning project yet. The current design is:

- local memory from trusted historical labels
- retrieval of relevant prior examples
- OpenAI used only when needed to improve categorization

## High-Level Design

The app has three user-facing workflows:

1. Import categorization memory
   Upload a labeled historical CSV and store trusted category examples locally.

2. Inspect categorization memory
   Retrieve the stored memory in a human-readable format so you can verify what the system knows.

3. Recategorize future transactions
   Upload a new CSV, retrieve relevant historical examples, and return suggested categories for the new transactions.

The long-term intent is:

- use exact or strong merchant matches as cheap, rule-like memory
- use OpenAI only when memory alone is not enough
- keep token usage low by sending only the most relevant examples

## Categorization Memory

Categorization memory is the local knowledge base for this app.

Each memory item represents a trusted historical labeling example, such as:

```json
{
  "merchant": "Electrify America",
  "amount": -7.0,
  "corrected_category": "Electric Vehicle Charging",
  "notes": "EV charging merchant"
}
```

Important design rules:

- `corrected_category` is the important label
- `original_category` is optional because historical data may not include it
- memory should come from trusted labeled history or explicit manual overrides
- not every AI suggestion should automatically become memory

## Category Reference

The app will also maintain a dedicated category reference file so categories stay consistent over time.

That reference should define:

- canonical category names
- category definitions
- aliases
- simple merchant patterns
- example merchants

This prevents drift like:

- `Transportation`
- `Auto & Transport`
- `Taxi & Ride Shares`

when they should be handled consistently.

## API Design

### `GET /health`

Basic health check.

### `POST /categorization-memory/import`

Upload a labeled historical CSV and import it into local categorization memory.

Expected CSV shape:

- required:
  - `merchant`
  - `amount`
  - `category`
- optional:
  - `date`
  - `original_category`
  - `notes`

Expected response:

```json
{
  "imported": 120,
  "skipped": 3
}
```

This endpoint should not call OpenAI.

### `GET /categorization-memory`

Return stored categorization memory in a human-readable JSON format.

Example response:

```json
[
  {
    "merchant": "Electrify America",
    "original_category": null,
    "corrected_category": "Electric Vehicle Charging",
    "notes": "EV charging merchant"
  }
]
```

This endpoint should not call OpenAI.

### `POST /recategorize-transactions-csv`

Upload a new transaction CSV and return category suggestions for future transactions.

Expected input CSV fields:

- `merchant`
- `amount`
- optional `date`
- optional `category`

Expected response:

```json
[
  {
    "date": "2026-03-24",
    "amount": -7.0,
    "merchant": "Electrify America",
    "original_category": "Gas",
    "suggested_category": "Electric Vehicle Charging",
    "reason": "Matches prior trusted labeling for the same merchant."
  }
]
```

This endpoint may call OpenAI, but only after retrieving a limited relevant subset of memory.

## User Workflow

A typical workflow should look like this:

1. Import historical labeled CSV data into categorization memory.
2. Inspect the stored memory to verify it looks correct.
3. Upload a new transaction CSV.
4. Receive corrected or improved suggested categories.

## Cost Control Strategy

The app should keep OpenAI usage low by default.

Planned controls:

- do not use OpenAI for memory import
- do not use OpenAI for memory retrieval
- retrieve only the top relevant memory examples
- cap context size
- prefer direct memory matches before calling the model

## Setup

Create and activate a virtual environment:

```fish
python3 -m venv .venv
source .venv/bin/activate.fish
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your environment file:

```bash
cp .env.example .env
```

Add your OpenAI API key to `.env`:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

## Run the Server

```bash
uvicorn main:app --reload
```

The API runs at `http://127.0.0.1:8000`.

## Run Tests

```bash
pytest
```

## Current Status

The repository already includes:

- CSV parsing
- recategorization with OpenAI
- request logging
- tests for parser and API behavior

The memory import and retrieval APIs are the next major build steps.

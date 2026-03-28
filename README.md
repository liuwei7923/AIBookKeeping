# AI Bookkeeping App MVP

Minimal FastAPI backend for:

- extracting transactions from an uploaded image using the OpenAI API
- importing transactions from CSV
- reviewing CSV categories with AI

## File Structure

```text
app/
├── main.py
├── requirements.txt
├── .env.example
└── README.md
```

## What It Does

Send a bank or credit card screenshot to the API and receive a JSON array like this:

```json
[
  {
    "date": "2026-03-01",
    "amount": -12.5,
    "merchant": "Starbucks",
    "category": null
  }
]
```

You can also upload a CSV file and either:

- import transactions directly
- ask AI to review and correct the categories

## Setup

1. Create and activate a virtual environment:

```fish
python3 -m venv .venv
source .venv/bin/activate.fish
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create your environment file:

```bash
cp .env.example .env
```

4. Add your OpenAI API key to `.env`:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

## Run the Server

```bash
uvicorn main:app --reload
```

The API will run at `http://127.0.0.1:8000`.

## Endpoints

### `GET /health`

Quick health check.

### `POST /extract-transactions`

Accepts an image upload with `multipart/form-data`.

Supported file types:

- JPEG
- PNG
- WEBP

### `POST /extract-transactions-csv`

Accepts a CSV upload with `multipart/form-data`.

The CSV should include a header row. Common column names are supported, including:

- `date`
- `transaction date`
- `amount`
- `merchant`
- `description`
- `payee`
- `category`

Returns the same JSON schema as the image endpoint:

```json
[
  {
    "date": "2026-03-01",
    "amount": -12.5,
    "merchant": "Starbucks",
    "category": "Coffee"
  }
]
```

### `POST /recategorize-transactions-csv`

Accepts the same CSV upload, then sends the parsed transactions to OpenAI to review the existing categories.

Returns:

```json
[
  {
    "date": "2026-03-01",
    "amount": -12.5,
    "merchant": "Starbucks",
    "original_category": "Shopping",
    "suggested_category": "Coffee",
    "reason": "Starbucks is typically a food and beverage purchase."
  }
]
```

## Sample cURL Request

Replace `sample.png` with your image file:

```bash
curl -X POST "http://127.0.0.1:8000/extract-transactions" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@sample.png"
```

### CSV Upload Example

Replace `transactions.csv` with your CSV file:

```bash
curl -X POST "http://127.0.0.1:8000/extract-transactions-csv" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@transactions.csv"
```

### AI Category Review Example

```bash
curl -X POST "http://127.0.0.1:8000/recategorize-transactions-csv" \
  -H "accept: application/json" \
  -F "file=@transactions.csv"
```

## Notes

- The app returns JSON only.
- If the uploaded file is invalid, the API returns an error.
- If the OpenAI request fails, the API returns a `502` error.
- CSV uploads are parsed directly and do not call the OpenAI API.
- AI category review for CSV uploads does call the OpenAI API.

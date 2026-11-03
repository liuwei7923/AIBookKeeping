# Prioritize bank statement input over downloaded transaction exports

**Status:** accepted

Downloaded transaction CSV exports vary by the time period selected and can include transactions in different states (pending vs. posted/closed), so the same transaction can appear more than once, or in conflicting forms, across separate downloads covering overlapping periods. Bank statements instead cover a fixed, non-overlapping period on a regular schedule and only include finalized transactions, so we're prioritizing bank statement input as the more standard, duplicate-resistant source for transaction data.

## Considered Options

- **Downloaded transaction CSV exports** — rejected as the primary input because overlapping date ranges and pending-to-posted status changes can produce duplicate or conflicting records for the same underlying transaction.

## Consequences

- Ingestion should be designed around statement-period boundaries rather than arbitrary user-selected date ranges.
- Fingerprint-based deduplication (see #19) remains useful for cross-statement overlap and manual re-imports, but is no longer the primary defense against pending/posted duplication.

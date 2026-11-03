# Merchant Identification Planning

This records proposed Phase 1 direction; it is not yet implemented.

- Preserve the source transaction description and identify a merchant separately. The merchant remains an important key for retrieving categorization memory.
- Look up relevant trusted merchant identifications before requesting model inference. Allow users to correct a merchant and treat their explicit correction as trusted evidence for future transactions.
- Introduce a replaceable MerchantReviewer for cases requiring model inference. The reviewer should support a fake client for tests and a path to local-model inference.
- Apply the existing AI-review approval threshold to merchant inference as well as category inference. The exact combined counting and approval behavior still needs to be specified.
- TODO: Define how transactions without a merchant, including transfers, payments, and fees, are identified, represented, reviewed, and categorized.
- TODO: Decide whether and when an unconfirmed AI-identified merchant can support an automatic categorization, rather than only retrieving evidence for review.
- TODO: Define safe matching and conflict handling for trusted merchant corrections, including user isolation and descriptions that may refer to multiple merchants.

## Decisions

### 2026-11-03: Trusted-merchant context enters before inference, not in the prompt

The merchant stage does not pass existing trusted merchant identifications into
the model prompt, unlike the category reviewer's `MAX_CATEGORY_CONTEXT_ITEMS`
window. Trusted context enters the stage before inference as a deterministic
lookup:

1. Look up the user's Trusted Merchant Identifications (normalized
   description/fingerprint matching) first. Exact matches resolve with no model
   call, matching the design goal that high-confidence repeated merchant
   matches avoid model calls whenever possible.
2. Only unresolved transactions go to `MerchantReviewer` (PR #76), which stays
   a pure suggestion engine.
3. The approval gate and confirmations wrap both outcomes.

Reasons against few-shot merchant context in the prompt: it spends tokens on
transactions the lookup can resolve deterministically, and it blurs the
contract because the model could echo a trusted merchant back, undermining
"suggestions, never confirmations".

Possible later refinement (not committed): after the lookup, feed a small list
of the user's existing merchants as few-shot context to improve naming
consistency for unknown variants. Revisit only if inconsistent names appear in
practice, and only alongside the safe-matching/conflict TODO above.

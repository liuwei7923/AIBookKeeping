# Merchant Identification Planning

This records proposed Phase 1 direction; it is not yet implemented.

- Preserve the source transaction description and identify a merchant separately. The merchant remains an important key for retrieving categorization memory.
- Look up relevant trusted merchant identifications before requesting model inference. Allow users to correct a merchant and treat their explicit correction as trusted evidence for future transactions.
- Introduce a replaceable MerchantReviewer for cases requiring model inference. The reviewer should support a fake client for tests and a path to local-model inference.
- Apply the existing AI-review approval threshold to merchant inference as well as category inference. The exact combined counting and approval behavior still needs to be specified.
- TODO: Define how transactions without a merchant, including transfers, payments, and fees, are identified, represented, reviewed, and categorized.
- TODO: Decide whether and when an unconfirmed AI-identified merchant can support an automatic categorization, rather than only retrieving evidence for review.
- TODO: Define safe matching and conflict handling for trusted merchant corrections, including user isolation and descriptions that may refer to multiple merchants.

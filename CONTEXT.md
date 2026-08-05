# AI Bookkeeping

This context describes the people and financial records managed by the bookkeeping application, including how it assigns, withholds, and reviews transaction categories. Its purpose is to keep multi-user bookkeeping decisions correctly isolated, auditable, and conservative when available evidence is incomplete.

## Language

**User**:
A person with a stable identity inside the bookkeeping application. A User is independent of any particular login provider or mutable contact information.
_Avoid_: Account, customer

**Development User**:
A synthetic User with a stable identity used for local development and
multi-user testing. It represents a product persona, not a software developer.
_Avoid_: Developer User, real user

**Source Transaction**:
A transaction preserved as received from an external source before identity and categorization processing.
_Avoid_: Raw transaction

**Canonical Transaction**:
A processed transaction represented in the application's shared vocabulary while preserving its source values, ownership, and normalized identity. Its identifier is unique within one recategorization request.
_Avoid_: Parsed row, API transaction, clean transaction

**Categorization Decision**:
The application's conclusion about a transaction's category, including the evidence and certainty supporting that conclusion.
_Avoid_: Prediction, label

**Accepted Category**:
A category selected by deterministic evidence and allowed to proceed without user review.
_Avoid_: Suggested category, proposed category

**Suggested Category**:
An existing category recommended by AI and requiring user review before it can become trusted.
_Avoid_: Accepted category, proposed category

**Proposed Category**:
A new category name proposed by AI that is not part of the known category set and requires user review.
_Avoid_: Suggested category, accepted category

**Unknown Categorization**:
A categorization decision intentionally left without a category because the available evidence is insufficient or conflicting. Unknown is a valid, safer outcome rather than an error.
_Avoid_: Uncategorized error, best guess

**Needs Review**:
A categorization decision presented to the user for confirmation because it is unknown or has evidence that its assigned category may be wrong.
_Avoid_: Failed

**Categorization Anomaly**:
An assigned category that is inconsistent with the transaction's historical patterns when evaluated over weekly, monthly, or quarterly windows. It is evidence for review, not proof that the category is wrong.
_Avoid_: Fraud, transaction anomaly

**Trusted Categorization**:
A category confirmed by the user or imported from a source explicitly designated as trustworthy. AI suggestions are not trusted categorizations until confirmed.
_Avoid_: High-confidence suggestion

**False Categorization**:
An assigned category that differs from the category the user confirms as correct. This is the primary failure the product is designed to minimize.
_Avoid_: Unknown categorization

**Recategorization Batch**:
An ordered set of canonical transactions and their categorization decisions produced for one request, together with its processing outcome.
_Avoid_: Review queue, OpenAI batch

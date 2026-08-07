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
A processed transaction represented in the application's shared vocabulary while preserving its source values, ownership, and normalized identity. Its identifier is globally unique and remains stable throughout the transaction's lifetime.
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

**Review Resolution**:
The human disposition of a review item: Pending, Confirmed, Corrected, or Kept Unknown. It is independent of the original Category Outcome, which remains unchanged for provenance.
_Avoid_: Category outcome, Accept AI

**Review Status**:
Whether a transaction review is To Do or Completed. Status describes workflow progress; a completed review separately records its Review Resolution.
_Avoid_: Category outcome, review resolution

**Review Record**:
The durable, immutable record of a completed human review, preserving the original Categorization Decision and the resulting Review Resolution.
_Avoid_: Review queue, categorization memory

**Evidence Condition**:
Whether the evidence behind a Categorization Decision is Supporting, Insufficient, or Conflicting. It constrains review actions without replacing the Category Outcome or review requirement.
_Avoid_: Confidence, review status

**Accept AI**:
The explicit review action that confirms a Suggested or Proposed Category when a category exists and evidence is not conflicting. The original AI outcome remains Suggested or Proposed after confirmation.
_Avoid_: Accepted Category

**Categorization Anomaly**:
An assigned category that is inconsistent with the transaction's historical patterns when evaluated over weekly, monthly, or quarterly windows. It is evidence for review, not proof that the category is wrong.
_Avoid_: Fraud, transaction anomaly

**Trusted Categorization**:
A category explicitly selected or confirmed by the user during transaction review. Bank-statement categories and AI suggestions are not trusted until the user reviews them.
_Avoid_: High-confidence suggestion

**Categorization Memory**:
The collection of Canonical Transactions that have a Trusted Categorization and may therefore serve as evidence for future Categorization Decisions.
_Avoid_: Training data, AI memory, categorization-memory item

**False Categorization**:
An assigned category that differs from the category the user confirms as correct. This is the primary failure the product is designed to minimize.
_Avoid_: Unknown categorization

**Recategorization Batch**:
An ordered set of canonical transactions and their categorization decisions produced for one request, together with its processing outcome.
_Avoid_: Review queue, OpenAI batch

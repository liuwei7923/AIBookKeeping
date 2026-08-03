# AI Bookkeeping

This context describes the people and financial records managed by the
bookkeeping application.

## Language

**User**:
A person with a stable identity inside the bookkeeping application. A User is
independent of any particular login provider or mutable contact information.
_Avoid_: Account, customer

**Source Transaction**:
A transaction preserved as received from an external source before identity and
categorization processing.
_Avoid_: Raw transaction

**Canonical Transaction**:
A processed transaction with normalized identity and categorization state.
_Avoid_: Clean transaction, normalized transaction

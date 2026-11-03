"""Compatibility alias for merchant and trusted merchant contracts."""

from bookkeeping_app.domain_contracts import (  # noqa: F401
    MerchantIdentificationStatus,
    TrustedMerchantIdentification,
    TrustedMerchantIdentificationSource,
)
from bookkeeping_app.trusted_merchants import *  # noqa: F403

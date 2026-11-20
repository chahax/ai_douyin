"""Independent source-v5 strict proof guard; historical verifier5 stays frozen."""
from src.content_factory.creative_flat_lineage_verifier_v6 import (
    VERSION, LineageVerificationError, VerificationCycle, build_lineage_certificate,
    digest, verify_lineage_certificate,
)

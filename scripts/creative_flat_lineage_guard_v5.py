"""Independent source-v4 strict proof guard; historical verifier4 stays frozen."""
from src.content_factory.creative_flat_lineage_verifier_v5 import (
    VERSION, LineageVerificationError, VerificationCycle, build_lineage_certificate,
    digest, verify_lineage_certificate,
)

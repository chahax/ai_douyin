"""Independent compact source-v3 proof guard; frozen v3 stays unchanged."""
from src.content_factory.creative_flat_lineage_verifier_v4 import (
    VERSION, LineageVerificationError, VerificationCycle, build_lineage_certificate,
    digest, verify_lineage_certificate,
)

"""Independent known605 consumption guard; historical v2 remains frozen."""
from src.content_factory.creative_flat_lineage_verifier_v3 import (
    VERSION,LineageVerificationError,VerificationCycle,build_lineage_certificate,
    digest,verify_lineage_certificate,
)

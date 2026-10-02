"""Final explicitly bound schema isolation case; same parent ledger and model."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import probe_repaired_creative_interface as probe
from scripts.creative_direction_source_schema import constrain_direction_sources
from jsonschema import Draft202012Validator

LABEL = "direction_source_enum"
_original_request_for = probe.request_for
_original_prior_valid = probe.prior_valid
_context = probe.read(probe.ROOT / "CONTEXT.json")
_messages, _base_schema = _original_request_for("direction")
_schema = constrain_direction_sources(_base_schema, _context)

def request_for(label):
    if label != LABEL:
        raise RuntimeError("this driver authorizes only the explicit source enum test")
    return _messages, _schema

def prior_valid(ledger, label):
    _original_prior_valid(ledger, "direction")  # micro success; all usages known.
    failed = next((c for c in ledger["calls"] if c["label"] == "direction"), None)
    if failed is None:
        raise RuntimeError("no original schema diagnostic to isolate")
    record = probe.read(probe.ROOT / failed["receipt"])
    if record["status"] != "validation_rejected" or record.get("failure", {}).get("code") != "MODULE_REQUIREMENT_SOURCE":
        raise RuntimeError("failure is outside this authorized schema-only isolation case")

class DirectionValidator:
    def __init__(self, schema):
        self.validator = Draft202012Validator(schema)
    def validate(self, output):
        self.validator.validate(output)
        probe.validate_direction(output, _context)

def main():
    binding = {
        "schema": "creative_diagnostic_contract_extension/v1",
        "created_at": probe.now(), "label": LABEL,
        "authorization": probe.AUTHORIZATION,
        "cause": "observed tool schema did not describe required script field paths",
        "changes": ["per-beat source path enum", "event cannot use unsupported during relation"],
        "messages_sha256_unchanged": probe.digest(_messages),
        "base_schema_sha256": probe.digest(_base_schema),
        "constrained_schema_sha256": probe.digest(_schema),
        "additional_sources": {str(p.relative_to(probe.PROJECT)).replace("\\", "/"):
                               hashlib.sha256(p.read_bytes()).hexdigest() for p in [
            Path(__file__).resolve(),
            probe.PROJECT / "scripts/creative_direction_source_schema.py"]},
        "model_temperature_thinking_messages_and_output_limit_unchanged": True,
        "parent_budget_reset": False, "automatic_retry": False,
        "complete_model_submission_required": True
    }
    path = probe.ROOT / "DIRECTION_SOURCE_ENUM_BINDING.json"
    if not path.exists():
        probe.write(path, binding, immutable=True)
    else:
        prior = probe.read(path)
        if {k:v for k,v in prior.items() if k!="created_at"} != {k:v for k,v in binding.items() if k!="created_at"}:
            raise RuntimeError("contract test binding differs; no dispatch")
    probe.LIMITS[LABEL] = 8000
    probe.request_for = request_for
    probe.prior_valid = prior_valid
    probe.Draft202012Validator = DirectionValidator
    result = probe.execute(LABEL)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(probe.report(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

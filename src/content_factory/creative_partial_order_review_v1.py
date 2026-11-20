"""Partial temporal proof and retained v4 non-temporal evidence checks.

No E/document index is treated as completed-time evidence. Native minimal
relations keep their quote proofs; this module checks their internal contract,
not whether a Chinese explanation actually proves causation.
"""
from copy import deepcopy
import unicodedata
from . import creative_split_full_review_contract_v4 as split

reviews = split.reviews
PART_TABLES = split.PART_TABLES
SEMANTIC_TABLES = split.SEMANTIC_TABLES
build_consistency_evidence_catalog = split.build_consistency_evidence_catalog


def temporal_proof(relations, catalog):
    """Validate native minimal relations; source IDs never imply time."""
    entries = {ref: row for ref, row in catalog.items() if row.get("kind") in ("action", "dialogue")}
    edges, overlaps, proofs = set(), set(), []
    for row in relations:
        if row["relation"] not in ("completed_before_start", "overlaps"):
            raise ValueError("unknown native temporal relation")
        left, right = row["from_ref"], row["to_ref"]
        if left not in entries or right not in entries or left == right:
            raise ValueError("native temporal relation requires two distinct current E steps")
        key = (row["relation"], left, right) if row["relation"] == "completed_before_start" else (row["relation"], *sorted((left, right)))
        if key in proofs:
            raise ValueError("duplicate native temporal relation")
        proofs.append(key)
        checked = set()
        for witness in row["evidence"]:
            ref, quote = witness["source_ref"], witness["quote"]
            if ref not in entries or not quote.strip() or quote not in catalog[ref]["quote"]:
                raise ValueError("temporal proof must quote its exact current source")
            checked.add(ref)
        if not {left, right} <= checked:
            raise ValueError("temporal relation must quote both actual E endpoints")
        if row["relation"] == "completed_before_start": edges.add((left, right))
        else: overlaps.add(frozenset((left, right)))
    adjacency = {ref: set() for ref in entries}
    for left, right in edges: adjacency[left].add(right)
    closure = set()
    # Reachability is bounded by O(V*(V+E)); never square the closure itself.
    for start in adjacency:
        pending, reached = list(adjacency[start]), set()
        while pending:
            node = pending.pop()
            if node == start:
                raise ValueError("native temporal proof contains a directed cycle")
            if node not in reached:
                reached.add(node); pending.extend(adjacency[node])
        closure.update((start, node) for node in reached)
    if any((a, b) in closure or (b, a) in closure for pair in overlaps for a, b in [tuple(pair)]):
        raise ValueError("native proven overlap conflicts with completed-before relation")
    return {"before": closure, "overlaps": overlaps, "native_relations": deepcopy(relations),
            "source_order_used": False, "semantic_proof_verified": False}


def related(temporal, left, right, *, allow_overlap=False):
    return bool(temporal and ((left, right) in temporal["before"] or
        allow_overlap and frozenset((left, right)) in temporal["overlaps"]))


def _target_source_allowed(temporal, entries, ref, beat_id, field):
    if entries[ref]["beat_id"] == beat_id: return True
    current = [key for key, row in entries.items() if row["beat_id"] == beat_id]
    return field == "trigger" and bool(current) and all(related(temporal, ref, key) for key in current)


def _physical_evidence(document, script, brief, *, opening_setup, temporal):
    old = reviews.base.base
    entries = old.prior.contract.evidence_catalog(script)
    initials = reviews.base.initial_evidence_catalog(brief, opening_setup)
    known = {(row["entity_id"], key): value for row in initials.values()
             for key, value in reviews.base._native_initial_atoms(row).items()}
    changes, uses, write_before = {}, {}, {}
    for ref, row in document["action_checks"].items():
        if row["status"] == "pass" and ref not in row["source_refs"]:
            raise ValueError("passing action must cite its own actual E")
        for entity in row["subjects"]: uses.setdefault(entity, set()).add(ref)
        changes[ref] = {}
        seen = set()
        for change in row["state_changes"]:
            atom = (change["entity_id"], change["state_key"])
            if atom[0] not in row["subjects"] or atom in seen:
                raise ValueError("state change must name a subject once per state key")
            seen.add(atom)
            for field in ("before", "after"): old._check_state_value(atom, change[field], brief)
            old._quote({"source_ref": ref, "quote": change["quote"]}, entries)
            if row["status"] == "pass":
                changes[ref][atom] = change["after"]
                write_before[ref, atom] = change["before"]

    def frontier(ref, atom):
        # Absence of a before edge is not proof that another write has not
        # happened. Incomparable writes to the same atom require an explicit
        # native ordering or an unresolved/failing check, never initial fallback.
        def verified_hold(other):
            return atom in known and old._same_value(write_before[other, atom], known[atom]) and old._same_value(changes[other][atom], known[atom])
        if any(other != ref and atom in changes[other]
                and not related(temporal, other, ref) and not related(temporal, ref, other)
                and not (verified_hold(other) and (atom not in changes.get(ref, {}) or verified_hold(ref)))
                for other in changes):
            return False, None
        writers = [other for other in changes if atom in changes[other] and related(temporal, other, ref)]
        last = [other for other in writers if not any(related(temporal, other, later) for later in writers)]
        values = [changes[other][atom] for other in last]
        if values and any(not old._same_value(value, values[0]) for value in values[1:]):
            return False, None
        return (True, values[0]) if values else ((True, known[atom]) if atom in known else (False, None))

    for ref, row in document["action_checks"].items():
        seen = set()
        for condition in row["preconditions"]:
            atom = (condition["entity_id"], condition["state_key"])
            if atom[0] not in row["subjects"] or atom in seen:
                raise ValueError("precondition must name a subject once per state key")
            seen.add(atom)
            for field in ("expected_value", "actual_value"): old._check_state_value(atom, condition[field], brief)
            origin = condition["established_by"]
            if origin is None:
                if row["status"] == "pass" or condition["actual_value"] is not None or condition["quote"]:
                    raise ValueError("unproved precondition requires unknown/fail, null actual and empty quote")
                continue
            if origin in initials:
                source = initials[origin]
                if source["entity_id"] != atom[0] or not condition["quote"].strip() or not any(
                        condition["quote"] in fragment for fragment in reviews.base._source_fragments(source["value"])):
                    raise ValueError("initial witness must quote the exact native setup entity")
                atoms = reviews.base._native_initial_atoms(source)
                if atom[1] not in atoms:
                    if row["status"] == "pass" or condition["actual_value"] is not None:
                        raise ValueError("native setup does not establish this required atom")
                    continue
                if not old._same_value(atoms[atom[1]], condition["actual_value"]):
                    raise ValueError("initial actual value differs from original setup atom")
                value = atoms[atom[1]]
                if row["status"] == "pass" and ((atom[1] == "open" and value is None) or
                        (atom[1] == "presence" and value in (None, "unknown")) or
                        (atom[1] in ("posture", "location") and value is None and source["value"].get("kind") != "absent")):
                    raise ValueError("unknown native initial atom cannot establish a pass")
            else:
                if not related(temporal, origin, ref):
                    raise ValueError("precondition requires a native proven completed-before E, not index or overlap")
                old._quote({"source_ref": origin, "quote": condition["quote"]}, entries)
                if atom not in changes.get(origin, {}) or not old._same_value(changes[origin][atom], condition["actual_value"]):
                    raise ValueError("precondition origin does not establish its reported state")
            established, value = frontier(ref, atom)
            if row["status"] == "pass" and (not old._same_value(condition["expected_value"], condition["actual_value"])
                    or not established or not old._same_value(value, condition["actual_value"])):
                raise ValueError("passing precondition lacks a unique compatible causal frontier")
        for change in row["state_changes"]:
            established, value = frontier(ref, (change["entity_id"], change["state_key"]))
            if row["status"] == "pass" and (not established or not old._same_value(value, change["before"])):
                raise ValueError("state change lacks a unique compatible proven causal frontier")
    for table in ("initial_checks", "observed_prop_initial"):
        for identifier, row in document[table].items():
            entity = identifier.split(":", 1)[1] if table == "initial_checks" else identifier
            actions = uses.get(entity, set())
            first = {ref for ref in actions if not any(related(temporal, other, ref) for other in actions)}
            if row["status"] == "pass" and first and not first <= set(row["source_refs"]):
                raise ValueError("passing initial check must cover every causally minimal actual use")
            if row["status"] == "pass" and any(related(temporal, first_ref, ref) for first_ref in first for ref in row["source_refs"]):
                raise ValueError("later proven actions cannot repair an initial-state check")

def _part_evidence(document, part, script, brief, plan, *, opening_setup=None, goal_contract=None, temporal=None):
    old = reviews.base.base
    entries = old.prior.contract.evidence_catalog(script)
    # These empty iteration sets are not missing audit rows or a native full
    # review. Only the owned, schema-complete actual rows are checked here.
    if part == "physical":
        selected = {table: deepcopy(document.get(table, {})) for table in
                    ("action_checks", "initial_checks", "observed_prop_initial")}
        selected.update(dialogue_checks={}, goal_checks={})
        _physical_evidence(selected, script, brief, opening_setup=opening_setup, temporal=temporal)
    else:
        refs = list(entries)
        for ref, row in document.get("dialogue_checks", {}).items():
            if row["status"] == "pass" and ref not in row["source_refs"]:
                raise ValueError("passing dialogue check must include its own actual dialogue reference")
            if not row["purpose"].strip() or not row["turn_function"].strip():
                raise ValueError("dialogue purpose and descriptive function must be substantive")
            if row["status"] == "pass" and row["stimulus_ref"] is not None and not related(temporal, row["stimulus_ref"], ref, allow_overlap=True):
                raise ValueError("dialogue stimulus must precede its actual dialogue step")
            if row["status"] == "pass" and any(not related(temporal, ref, reaction, allow_overlap=True) for reaction in row["reaction_refs"]):
                raise ValueError("dialogue reaction must follow its actual dialogue step")
        for row in document["goal_checks"].values():
            if row["status"] == "pass" and not row["evidence"]:
                raise ValueError("passing scene-goal check requires actual screenplay evidence")
            for witness in row["evidence"]:
                old._quote(witness, entries)
                if witness["source_ref"] not in row["source_refs"]:
                    raise ValueError("goal witness must be part of its actual source references")
    for table in PART_TABLES[part]:
        if table not in document or table in ("literal_events", "review_limitations", *SEMANTIC_TABLES, "unresolved_issues"):
            continue
        rows = document[table].values() if isinstance(document[table], dict) else document[table]
        for row in rows:
            if row["status"] == "pass" and row["required_revision"]:
                raise ValueError("passing check cannot carry a mandatory revision")
            if row["status"] == "fail" and not row["required_revision"].strip():
                raise ValueError("failed check needs an explicit complete revision target")
    if part == "physical":
        props = {row["id"]: row for row in brief["initial_state"]["prop_states"]}
        for identifier, row in document.get("observed_prop_initial", {}).items():
            if row["status"] == "pass" and any(row[field] != props[identifier][field]
                for field in ("holder_character_id", "support", "orientation")):
                raise ValueError("passed actual initial prop atoms conflict with frozen native declarations")
        return
    literal = document.get("literal_events", {})
    for ref, row in literal.items():
        if (entries[ref]["kind"] == "action" and row["speech_functions"] != ["action"]
                or entries[ref]["kind"] == "dialogue" and "action" in row["speech_functions"]):
            raise ValueError("literal speech functions conflict with original step kind")
    positions = {ref: index for index, ref in enumerate(entries)}

    def occurrence(item):
        quote = item["quote"]
        ref = item["source_ref"]
        if not quote.strip() or quote not in entries[ref]["quote"]:
            raise ValueError("occurrence quote must come from the unchanged actual step")
        if not set(item["speech_functions"]).issubset(literal[ref]["speech_functions"]):
            raise ValueError("occurrence invents a speech function")
        start = entries[ref]["quote"].find(quote)
        return ref, start, start + len(quote)

    obligations = {row["id"]: row for row in plan["source_obligations"]}
    seen = {}
    for identifier, row in document.get("obligations", {}).items():
        spec = obligations[identifier]
        keys = set()
        for witness in row["occurrence_evidence"]:
            occurrence(witness)
            key = (witness["source_ref"], witness["quote"])
            if key in keys:
                raise ValueError("duplicate occurrence evidence")
            keys.add(key)
            if spec["mode"] == "event" and row["status"] == "pass":
                actual = entries[witness["source_ref"]]
                if spec["required_kind"] != "either" and actual["kind"] != spec["required_kind"]:
                    raise ValueError("event witness has wrong step kind")
                if not set(spec["allowed_speech_functions"]) & set(witness["speech_functions"]):
                    raise ValueError("event witness lacks the required speech function")
                if (spec["actor_id"] in brief["constraints"]["allowed_character_ids"]
                        and spec["required_kind"] == "dialogue" and actual["speaker"] != spec["actor_id"]):
                    raise ValueError("event witness has wrong on-screen speaker")
        if row["status"] == "pass" and spec["mode"] == "event" and not keys:
            raise ValueError("passed event must actually occur")
        seen[identifier] = keys
    for identifier, spec in obligations.items():
        row = document["obligations"][identifier]
        if row["status"] != "pass" or spec["mode"] != "event":
            continue
        for other in spec.get("distinct_from_ids", []):
            other_row = document["obligations"][other]
            if other_row["status"] != "pass":
                continue
            for left in row["occurrence_evidence"]:
                for right in other_row["occurrence_evidence"]:
                    a, b = occurrence(left), occurrence(right)
                    if a[0] == b[0] and max(a[1], b[1]) < min(a[2], b[2]):
                        raise ValueError("distinct events cannot share an overlapping occurrence")
    for identifier, row in document.get("order_checks", {}).items():
        before_id, after_id = identifier.split(">")
        if row["status"] == "pass" and (not row["before"] or not row["after"]):
            raise ValueError("passed strict order needs actual witnesses")
        for key, source_id in (("before", before_id), ("after", after_id)):
            for witness in row[key]:
                occurrence(witness)
                if (witness["source_ref"], witness["quote"]) not in seen[source_id]:
                    raise ValueError("strict-order witness is not an occurrence of its obligation")
        if row["status"] == "pass" and not all((related(temporal, occurrence(a)[0], occurrence(b)[0])
                or occurrence(a)[0] == occurrence(b)[0] and occurrence(a)[2] <= occurrence(b)[1])
                for a in row["before"] for b in row["after"]):
            raise ValueError("strict order is not shown by nonoverlapping occurrences")
    for row in document["legal_claims"]:
        if not row["quote"].strip() or row["quote"] not in entries[row["source_ref"]]["quote"]:
            raise ValueError("legal claim is not quoted from the actual text")
        if row["status"] == "pass" and not row["legal_fact_refs"]:
            raise ValueError("passed legal claim needs independent legal support")
    if "prior_story_relation" in document:
        relation = document["prior_story_relation"]
        if not relation["reason"].strip():
            raise ValueError("prior-story relation needs a substantive reason")
        for witness in relation["current_evidence"]:
            old._quote(witness, entries)
    _validate_semantic_evidence(document, script, plan, goal_contract=goal_contract, temporal=temporal)

def _validate_semantic_evidence(document, script, plan, *, goal_contract=None, temporal=None):
    """Check reported meaning bindings, never independently interpret prose."""
    catalog = build_consistency_evidence_catalog(script, plan, goal_contract=goal_contract)
    entries, targets = catalog["actual_steps"], catalog["target_assertions"]
    beat_position = {beat["id"]: index for index, beat in enumerate(script["beats"])}

    def quote(witness):
        ref = witness["source_ref"]
        if ref not in entries or not witness["quote"].strip() or witness["quote"] not in entries[ref]["quote"]:
            raise ValueError("semantic witness must quote an unchanged actual E step, never a target assertion")

    def judgment(row, *, own_ref=None):
        for witness in [*row["evidence"], *row["counterevidence"]]:
            quote(witness)
        if row["status"] == "pass":
            if row["required_revision"] or row["counterevidence"]:
                raise ValueError("passing semantic check cannot hide a mandatory revision or unresolved counterevidence")
            if not row["evidence"]:
                raise ValueError("passing semantic check needs actual E evidence")
            if own_ref is not None and not any(item["source_ref"] == own_ref for item in row["evidence"]):
                raise ValueError("passing dialogue-role check needs its own actual E quote")
        elif row["status"] == "fail" and not row["required_revision"].strip():
            raise ValueError("failed semantic check needs an explicit complete revision target")

    def aggregate(row, children):
        # Unknown has priority over definite failure, matching the dispatch
        # boundary. A model cannot hide one uncertain subcheck in a passing row.
        expected = "unknown" if any(item["status"] == "unknown" for item in children) else (
            "fail" if any(item["status"] == "fail" for item in children) else "pass")
        if row["status"] != expected:
            raise ValueError("semantic row status must preserve its reported subcheck failure or uncertainty")

    issue_targets = set()
    for issue in document["unresolved_issues"]:
        table, identifier = issue["table"], issue["item_id"]
        pointer = (table, identifier)
        if pointer in issue_targets:
            raise ValueError("each concrete unresolved target must appear once")
        issue_targets.add(pointer)
        rows = document[table]
        if isinstance(rows, list):
            if type(identifier) is not int or not 0 <= identifier < len(rows):
                raise ValueError("unresolved issue must identify an existing native array row")
        elif identifier not in rows:
            raise ValueError("unresolved issue must identify an existing native coverage row")
        if rows[identifier]["status"] != issue["status"]:
            raise ValueError("concrete unresolved issue cannot be hidden behind a passing or different-status native table row")

    for beat_id, row in document["beat_intent_checks"].items():
        checks = list(row["target_checks"].values())
        aggregate(row, checks)
        for ref, item in row["target_checks"].items():
            judgment(item)
            target = targets[ref]
            if item["status"] == "pass" and any(not _target_source_allowed(temporal, entries, w["source_ref"], beat_id, target["field"])
                   for w in item["evidence"]):
                raise ValueError("later beat cannot supply the current target's performed evidence")
            # A trigger may be established in an earlier beat. The current
            # event needs an actual step in this beat; neither uses metadata.
            earlier_allowed = target["field"] == "trigger"
            if item["status"] == "pass" and not earlier_allowed and not any(
                    entries[w["source_ref"]]["beat_id"] == beat_id for w in item["evidence"]):
                raise ValueError("passing current beat intent needs an actual step from that beat")
    for ref, row in document.get("dialogue_role_checks", {}).items():
        checks = list(row["checks"].values())
        aggregate(row, checks)
        for item in checks:
            judgment(item, own_ref=ref)
        if row["listener_mode"] == "self_talk" and row["listener_id"] not in (None, row["speaker_id"]):
            raise ValueError("self-talk cannot report a different addressed listener")
        if row["listener_mode"] == "unspecified" and row["listener_id"] is not None:
            raise ValueError("unspecified listener must remain null")
        if row["listener_mode"] == "addressed" and row["listener_id"] is None and row["status"] == "pass":
            raise ValueError("passing addressed dialogue must identify its listener")
        attribution = row["quote_attribution"]
        fragment = attribution["quote_fragment"]
        if attribution["mode"] == "none":
            if fragment is not None or attribution["attributed_to"]["kind"] != "unspecified":
                raise ValueError("unquoted speech cannot invent a quote attribution")
        elif not isinstance(fragment, str) or not fragment.strip() or fragment not in row["quote"]:
            raise ValueError("quote attribution must bind a real fragment of its actual dialogue")
        covered = set()
        for proposition in row["propositions"]:
            fragment = proposition["quote"]
            text = row["quote"]
            if fragment not in text:
                raise ValueError("proposition must bind an exact fragment of its own actual dialogue")
            # Locate all identical occurrences; overlapping fragments are legal
            # for compound predicates and do not force one unique subject.
            start = text.find(fragment)
            while start >= 0:
                covered.update(range(start, start + len(fragment)))
                start = text.find(fragment, start + 1)
            negation = proposition["negation"]
            scope = negation["scope_quote"]
            if negation["mode"] == "affirmed" and scope is not None:
                raise ValueError("affirmative proposition cannot report a negation scope")
            if negation["mode"] == "negated" and (not isinstance(scope, str) or not scope.strip() or scope not in fragment):
                raise ValueError("reported negation scope must quote the actual proposition fragment")
            if scope is not None and (not scope.strip() or scope not in fragment):
                raise ValueError("reported proposition scope must quote its actual fragment")
        if any(index not in covered and not char.isspace() and not unicodedata.category(char).startswith("P")
               for index, char in enumerate(row["quote"])):
            raise ValueError("dialogue propositions must bind every substantive character of the actual line")

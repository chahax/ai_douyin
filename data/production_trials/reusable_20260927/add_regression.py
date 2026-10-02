from pathlib import Path
p=Path('tests/test_reusable_production.py');s=p.read_text(encoding='utf-8');needle='    before = len(clients.calls)\n';replacement='''    receipt = read(run / "director_production_design.json")
    assert receipt["status"] == "validated"
    assert receipt["output"] == read(run / "PRODUCTION_DESIGN.json")
    assert receipt["request"]["messages"]
    from scripts.revise_creative_from_assistant import bound_workflow
    _, restored = bound_workflow(run)
    assert restored.metadata["creative_brief"] == bundle.metadata["creative_brief"]
    assert restored.manifest == bundle.manifest
    before = len(clients.calls)
''';assert needle in s;s=s.replace(needle,replacement,1);p.write_text(s,encoding='utf-8')

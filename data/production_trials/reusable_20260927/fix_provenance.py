from pathlib import Path
import json,shutil
base=Path('data/production_trials/reusable_20260927'); backup=base/'code_before_fixes';backup.mkdir(exist_ok=True)
for name in ('src/content_factory/creative_workflow.py','src/content_factory/creative_workflow_contract.py','scripts/revise_creative_from_assistant.py'):
 p=Path(name);shutil.copyfile(p,backup/name.replace('/','__'))
p=Path('src/content_factory/creative_workflow.py');s=p.read_text(encoding='utf-8');s=s.replace('"production_design", "director",','"director_production_design", "director",').replace('f"production_design__assistant_{round_index:02}"','f"director_production_design__assistant_{round_index:02}"');p.write_text(s,encoding='utf-8')
p=Path('src/content_factory/creative_workflow_contract.py');s=p.read_text(encoding='utf-8');s+='\n# Distinct receipt name on case-insensitive filesystems.\nPROMPTS["director_production_design"] = DESIGN_PROMPT\n';p.write_text(s,encoding='utf-8')
p=Path('scripts/revise_creative_from_assistant.py');s=p.read_text(encoding='utf-8');s=s.replace('        reference_paths=references,','        reference_paths=references,\n        brief_path=Path(files["creative_brief"]["path"]) if "creative_brief" in files else None,\n        asset_library_path=Path(files["asset_library"]["path"]) if "asset_library" in files else None,');p.write_text(s,encoding='utf-8')

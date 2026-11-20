import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
source = ROOT / 'data/production_trials/fanqie_full_two_minutes_20261117_v1/original_publication_diagnostic_request_v2/capture/SAMPLE_03.json'
value = json.loads(source.read_text(encoding='utf8'))
label = value['discovery']['diagnostic']['bound_title_structure']['ancestors'][0]['projected_outer_html']
markup = '''<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:20px}.video-card-sfaSzz{width:1000px;margin:12px}
.video-card-content-Xt386b{display:flex;width:990px;height:180px;gap:16px}
.video-card-cover-QkeRHf{cursor:pointer;width:120px;height:160px;background:#aaa;position:relative;flex-shrink:0}
.video-card-top-eL6bwF{height:48px}.video-card-bottom-cq09K3{height:108px}
.video-card-info-dzTKoo{width:850px}.info-title-text-Zob9RV{height:20px;width:480px;overflow:hidden;white-space:nowrap}
.ops{display:flex;gap:12px}.notpass-info-upwAoZ{cursor:pointer}
</style></head><body><div class="video-card-sfaSzz video-card-new-e033na">
<div class="video-card-content-Xt386b"><div class="video-card-cover-QkeRHf">
<div class="video-card-top-eL6bwF"></div><div class="video-card-bottom-cq09K3"></div></div>
<div class="video-card-info-dzTKoo">''' + label + '''<div class="ops">
<span>编辑作品</span><span>设置权限</span><span>作品置顶</span><span>删除作品</span></div>
<div class="info-time-tP3i_r">2026年11月17日 09:37</div><div class="info-status-QukAhD">流量减少</div>
<div class="notpass-info-upwAoZ">查看详情</div></div></div></div></body></html>'''
target = Path(__file__).with_name('observed_card.html')
target.write_text(markup,encoding='utf8')
bind = lambda p: dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
Path(__file__).with_name('SOURCE.json').write_text(json.dumps(dict(source=bind(source),fixture=bind(target),
    kind='minimal_reconstruction_from_sanitized_observed_class_shape_and_exact_caption',
    omitted='metric SVGs, images, platform links and private data; no signed URLs',
    status_text='流量减少',legacy_published_leaf_absent=True),ensure_ascii=False,indent=2),encoding='utf8')

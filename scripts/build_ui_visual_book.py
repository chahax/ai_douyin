"""Create a small offline visual book from source evidence, not fabricated screenshots."""
import ast
import base64
import html
import json
import zipfile
import subprocess
import sys
import types
from pathlib import Path
from build_full_ui_comparison import BASE

OUT = BASE / 'visual-book'
DATA = json.loads((BASE / 'gallery/source-comparison.json').read_text(encoding='utf-8'))
ROOT = BASE.parents[2]


def navigation():
    result = {'old': [], 'new': []}
    old_tree = ast.parse((BASE / 'legacy/src/web/app.py').read_text(encoding='utf-8-sig'))
    for n in sorted(ast.walk(old_tree), key=lambda n: getattr(n, 'lineno', 0)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'Page':
            kw = {k.arg: ast.literal_eval(k.value) for k in n.keywords if isinstance(k.value, ast.Constant)}
            result['old'].append(dict(function=n.args[0].id, title=kw['title'], icon=kw['icon'], group=''))
    new_tree = ast.parse((ROOT / 'src/web/app.py').read_text(encoding='utf-8-sig'))
    spec = next(n.value for n in new_tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'nav_spec' for t in n.targets))
    for group, entries in zip(spec.keys, spec.values):
        for entry in entries.elts:
            e = entry.elts
            result['new'].append(dict(id=ast.literal_eval(e[0]), function=e[1].id, title=ast.literal_eval(e[2]), icon=ast.literal_eval(e[3]), group=ast.literal_eval(group)))
    return result


NAV = navigation()
ICON_PATHS = {}


def load_icons():
    # Decode the installed Streamlit font with Node's bundled Brotli, without installing packages.
    shim = types.ModuleType('brotli')
    shim.decompress = lambda data: subprocess.run(['node', '-e', 'const z=require("zlib"),fs=require("fs");process.stdout.write(z.brotliDecompressSync(fs.readFileSync(0)));'], input=data, capture_output=True, check=True).stdout
    sys.modules.setdefault('brotli', shim)
    from fontTools.ttLib import TTFont
    from fontTools.pens.svgPathPen import SVGPathPen
    font = TTFont(next((ROOT / '.venv/Lib/site-packages/streamlit/static/static/media').glob('MaterialSymbols*.woff2')))
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    ligatures = {}
    for lookup in font['GSUB'].table.LookupList.Lookup:
        for sub in lookup.SubTable:
            sub = getattr(sub, 'ExtSubTable', sub)
            for first, entries in getattr(sub, 'ligatures', {}).items():
                for entry in entries:
                    ligatures[tuple([first] + entry.Component)] = entry.LigGlyph
    for entry in NAV['new']:
        name = entry['icon']
        key = tuple(cmap[ord(c)] for c in name)
        glyph_name = ligatures.get(key, name if name in glyphs else None)
        if not glyph_name:
            raise ValueError(f'Missing original icon: {name}')
        pen = SVGPathPen(glyphs)
        glyphs[glyph_name].draw(pen)
        ICON_PATHS[name] = (pen.getCommands(), font['head'].unitsPerEm)


def esc(s):
    return html.escape(str(s))


def wrap(text, width=47):
    lines, line, units = [], '', 0
    for c in str(text):
        size = 1 if ord(c) < 128 else 2
        if units + size > width:
            lines.append(line)
            line, units = '', 0
        line += c
        units += size
    return lines + ([line] if line else [])


def scene(p, version):
    old = version == 'old'
    bg, surface, text, muted, line, accent = ('#f6f6fa', '#ffffff', '#181921', '#777986', '#e9e9f0', '#655cf6') if old else ('#101114', '#191b20', '#f0f1f3', '#a1a5b0', '#2b2e36', '#bcf56b')
    parts = []
    def rect(x,y,w,h,fill,stroke='none',r=10):
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}"/>')
    def txt(x,y,s,size=15,color=None,bold=False):
        parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color or text}" font-weight="{650 if bold else 400}">{esc(s)}</text>')
    rect(0,0,1120,1000,bg,r=0)
    rect(0,0,212,1000,'#16171f' if old else '#141519',r=0)
    if not old:
        logo = (ROOT / 'src/web/components/studio_logo.svg').read_bytes()
        parts.append('<image x="16" y="17" width="185" height="40" href="data:image/svg+xml;base64,'+base64.b64encode(logo).decode()+'"/>')
    else:
        txt(20,38,'页面导航',20,'#ffffff',True)
    y, group = 96, None
    for page in NAV[version]:
        if not old and group != page['group']:
            txt(20,y,page['group'],12,'#a1a5b0')
            y += 25
            group = page['group']
        active = page.get('id') == p['id'] if not old else bool(p['old'] and page['function'] == p['old']['function'])
        if active:
            rect(12,y-18,186,30,accent if old else '#293323',r=7)
        color = ('#ffffff' if old else accent) if active else '#adb2be'
        if old:
            txt(22,y+2,page['icon'],16,color)
        else:
            path, units = ICON_PATHS[page['icon']]
            scale = 17 / units
            parts.append(f'<path d="{path}" fill="{color}" transform="translate(22 {y+3}) scale({scale} {-scale})"/>')
        txt(49,y+2,page['title'],13,color)
        y += 35 if old else 33
    txt(240,34,'源码结构示意 · 非真实截图 · 无业务数据',12,muted)
    txt(240,83,p['title'].split(' / ')[0],28,bold=True)
    txt(240,111,'浅色紫系 / 历史基线' if old else '深石墨青柠 / 当前工作树',13,muted)
    source = p[version]
    if not source:
        rect(280,275,780,285,surface,line,16)
        txt(328,355,'旧版没有这个页面',32,muted,True)
        txt(328,407,'这是新版新增功能，不制作虚构的旧版截图。',18,muted)
        txt(328,454,'请看右侧新版内容与导航入口。',16,muted)
    elif p['id']=='home':
        rect(240,146,846,218,'#202a1c',line,16)
        txt(270,186,'AI DOUYIN / CREATIVE WORKSPACE',12,accent)
        txt(270,242,'让好选题，成为好内容。',36,bold=True)
        txt(270,291,'从发现灵感到打磨作品，把选题、制作与运营连接起来。',17,muted)
        for i,(title,sub) in enumerate([('发现热门选题','追踪趋势 · 内容调研 · 脚本草案'),('打磨视频作品','剧本与分镜 · 制作进度 · 成片审核'),('管理内容运营','作品同步 · 人工发布 · 互动反馈')]):
            x=240+i*286
            rect(x,385,274,160,['#252d21','#2a2433','#1e2c33'][i],line,14)
            txt(x+20,421,f'0{i+1} / WORKSPACE',11,accent)
            txt(x+20,465,title,22,bold=True)
            for j,t in enumerate(wrap(sub,29)):
                txt(x+20,494+j*19,t,13,muted)
        txt(240,592,'最近制作',22,bold=True)
        rect(240,615,846,138,surface,line,14)
        txt(268,672,'项目卡片区域',20,bold=True)
        txt(268,707,'动态项目内容不在此示意图中填造。',15,muted)
        txt(240,800,'运营一览',22,bold=True)
        for i,label in enumerate(['已发布作品','收到评论','已回复评论','评论回复率']):
            rect(240+i*215,823,201,103,surface,line,14)
            txt(257+i*215,855,label,14,muted)
            txt(257+i*215,896,'—',25)
    else:
        # Convert source UI call points to a schematic control sheet in source order.
        tree=ast.parse(source['source'])
        items=[]
        supported={'tabs','expander','text_input','text_area','selectbox','multiselect','radio','checkbox','toggle','number_input','button','form_submit_button','metric','header','subheader','section_header','file_uploader','dataframe','data_editor','chat_input'}
        for n in sorted((n for n in ast.walk(tree) if isinstance(n,ast.Call)),key=lambda n:(n.lineno,n.col_offset)):
            method=n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id if isinstance(n.func,ast.Name) else ''
            if method not in supported:
                continue
            try:
                label=ast.literal_eval(n.args[0]) if n.args else ''
            except (ValueError,TypeError):
                label='动态内容区域' if method in {'dataframe','data_editor'} else None
            if label is not None:
                items.append((method,' / '.join(map(str,label)) if isinstance(label,(list,tuple)) else str(label)))
        y=148
        if p['id']=='production':
            for i,label in enumerate(['01 灵感来源','02 分析依据','03 剧本内容','04 分镜与采集','05 合并成片','06 一致性审核','07 本地文件','08 页面风格']):
                x=240+(i%4)*214
                rect(x,y+(i//4)*62,202,50,surface,accent if i==1 else line,10)
                txt(x+12,y+31+(i//4)*62,label,16,accent if i==1 else text)
            y+=142
        shown=0
        for method,label in items:
            if y>835:
                break
            label_lines=wrap(label,93)
            if method in {'header','subheader','section_header'}:
                for t in label_lines[:2]:
                    txt(240,y+25,t,20,bold=True)
                    y+=29
                y+=14
            elif method in {'button','form_submit_button'}:
                height=24+22*min(2,len(label_lines))
                rect(240,y,846,height,accent,r=9)
                for j,t in enumerate(label_lines[:2]):
                    txt(258,y+28+j*22,t,15,'#ffffff' if old else '#16210c',True)
                y+=height+16
            elif method in {'tabs','radio'}:
                rect(240,y,846,52,surface,line,10)
                for j,t in enumerate(label_lines[:2]):
                    txt(258,y+22+j*21,t,14,accent)
                y+=68
            elif method in {'dataframe','data_editor'}:
                rect(240,y,846,100,surface,line,10)
                txt(258,y+30,'数据表区域',16,bold=True)
                txt(258,y+65,'动态记录省略 · 未读取数据库',14,muted)
                y+=116
            elif method=='metric':
                rect(240,y,846,79,surface,line,14)
                txt(258,y+28,label_lines[0],14,muted)
                txt(258,y+62,'—',24)
                y+=95
            else:
                for t in label_lines[:2]:
                    txt(240,y+18,t,15)
                    y+=22
                height=66 if method in {'text_area','file_uploader'} else 40
                rect(240,y+6,846,height,surface,line,9)
                txt(257,y+32,'展开内容（示意）' if method=='expander' else '输入 / 选择内容（示意）',13,muted)
                y+=height+24
            shown+=1
        if not items:
            rect(240,y,846,190,surface,line,14)
            txt(270,y+52,'此页面主要由辅助模块或动态内容构成',22,bold=True)
            txt(270,y+99,'本图只展示公共主题与页面入口，不虚构业务布局。',16,muted)
        if shown<len(items):
            txt(240,934,f'首屏结构节选 · 另有 {len(items)-shown} 个静态调用点未在本图展开',12,muted)
    txt(240,972,'版式为统一示意，不复原像素位置；条件分支可能不会同时出现在实际页面。',12,muted)
    return '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="1000" viewBox="0 0 1120 1000"><title>'+esc(p['title']+' '+version+' 源码结构示意')+'</title><g font-family="Microsoft YaHei,Arial,sans-serif">'+''.join(parts)+'</g></svg>'


def main():
    load_icons()
    (OUT/'images').mkdir(parents=True,exist_ok=True)
    rows=[]
    for p in DATA['pages']:
        item={k:p[k] for k in ['id','title','group','status']}
        for version in ['old','new']:
            s=scene(p,version)
            (OUT/'images'/f'{p["id"]}-{version}.svg').write_text(s,encoding='utf-8')
            item[version]='data:image/svg+xml;base64,'+base64.b64encode(s.encode()).decode()
            item[version+'_evidence']='源码结构示意 · 非页面实拍'
        # Preserve user-provided pixels, rather than drawing another approximate home.
        if p['id'] == 'home':
            screenshot = Path('C:/Users/c/AppData/Local/Temp/codex-clipboard-2943c459-61a8-4036-89d8-fd1e62dc5b16.png')
            saved = OUT / 'images/home-new-reference.png'
            if screenshot.exists():
                saved.write_bytes(screenshot.read_bytes())
            if saved.exists():
                item['new'] = 'data:image/png;base64,'+base64.b64encode(saved.read_bytes()).decode()
                item['new_evidence'] = '用户提供的新版真实截图 · 原图保留'
        if p['id'] == 'login':
            for version in ['old','new']:
                screenshot = BASE / f'screenshots/login-{version}.png'
                if screenshot.exists():
                    saved = OUT / f'images/login-{version}-reference.png'
                    saved.write_bytes(screenshot.read_bytes())
                    item[version] = 'data:image/png;base64,'+base64.b64encode(saved.read_bytes()).decode()
                    item[version+'_evidence'] = '此前隔离预览截图 · 登录页'
        rows.append(item)
    template=Path(__file__).with_name('ui_visual_book_template.html').read_text(encoding='utf-8')
    replacements = {
        '20 组 · 左旧右新 · 根据源码生成的主题与控件结构示意，非真实截图／像素级还原。动态数据省略，部分条件分支合并展示。':
        '修订版 · 20 组左旧右新。新版首页使用你提供的截图；登录页使用此前预览截图。其余为结构示意：导航名称、顺序及图标已按源码修正，但内容布局仍非像素级还原。',
        '2c0d8d5 · 2026-09-01</small>': '2c0d8d5 · 2026-09-01</small><small id="oldEvidence"></small>',
        '当前代码 · 2026-09-06</small>': '当前代码 · 2026-09-06</small><small id="newEvidence"></small>',
        "$('status').textContent=p.status;": "$('status').textContent=p.status;$('oldEvidence').textContent=p.old_evidence;$('newEvidence').textContent=p.new_evidence;",
        "$('old').alt=p.title+' · 旧版结构示意';$('new').alt=p.title+' · 新版结构示意';":
        "$('old').alt=p.title+' · '+p.old_evidence;$('new').alt=p.title+' · '+p.new_evidence;",
        "+' · 结构示意（非实拍）'": "+' · '+pages[index][v+'_evidence']",
        'show(0);': 'show(1);',
    }
    for before, after in replacements.items():
        if before == after:
            continue
        assert before in template, before
        template = template.replace(before, after)
    payload=json.dumps(rows,ensure_ascii=False).replace('<','\\u003c')
    (OUT/'index.html').write_text(template.replace('__DATA__',payload),encoding='utf-8')
    with zipfile.ZipFile(BASE/'visual-comparison-book.zip','w',zipfile.ZIP_DEFLATED) as z:
        z.write(OUT/'index.html','index.html')
        for p in (OUT/'images').glob('*'):
            z.write(p,'images/'+p.name)
    print(json.dumps({'pages':len(rows),'images':len(list((OUT/'images').glob('*.svg'))),'html_bytes':(OUT/'index.html').stat().st_size,'file':str(OUT/'index.html')}))


if __name__=='__main__':
    main()

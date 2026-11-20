import bpy,importlib.util,sys,json
from pathlib import Path
root=Path('D:/IT/ai_douyin/tools/scene_lab_20261006')
addon=next((root/'sources/ahujasid__blender-mcp').glob('*/src/blender_mcp/bundled/addon.py'))
spec=importlib.util.spec_from_file_location('scene_lab_blender_addon',addon);module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
module.register()
server=module.BlenderMCPServer(host='127.0.0.1',port=9878);server.start()
(root/'geometry/BLENDER_MCP_READY.json').write_text(json.dumps({'running':server.running,'port':9878,'addon_protocol':module.ADDON_PROTOCOL_VERSION,'scene':bpy.data.filepath,'background':bpy.app.background}),encoding='utf-8')

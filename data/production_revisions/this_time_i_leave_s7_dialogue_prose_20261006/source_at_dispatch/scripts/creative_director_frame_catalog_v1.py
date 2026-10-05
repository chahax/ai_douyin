"""Camera-only framing presets: no body/prop actions or creative approvals."""
VERSION='editorial_frame_catalog/v1'
FRAMES={
 'office_wide':{'camera':'从两人工位前侧拍固定中景，深景深，交代空间与桌面物件；不设定动作完成后的初态','composition':'两人工位与脸部、当前桌面物件同框，保留人物实际站坐高度差','visible':['C01_face','C02_face','C02_mouth','tables'],'dialogue_modes':['无对白']},
 'dual_front':{'camera':'从工位前侧拍固定双人中近景，保持两人面部、眼睛和嘴同时清晰；不从背后拍','composition':'两人半侧脸同框，桌面位于下沿，避免前实后虚遮蔽听者','visible':['C01_face','C02_face','C02_mouth','tables'],'dialogue_modes':['画内对白','无对白']},
 'table_hands':{'camera':'桌面斜俯近景，手与当前源道具清晰，嘴不入画；拍完整原动作，不额外切镜','composition':'三色便利贴及握笔手在桌面近景可读，不改变当前持有、朝向或支持面','visible':['hands','notes','pen'],'dialogue_modes':['画外对白','无对白']},
 'fang_face_pen':{'camera':'前侧方澄面部中近景，眼区清晰，递向她的笔在画面下沿作陪体','composition':'方澄脸部为主，笔及握笔手在下沿，不遮挡她从笔抬眼的目光','visible':['C01_face','pen'],'dialogue_modes':['无对白']},
 'fang_face':{'camera':'前侧方澄面部近景，固定镜头完整容纳两句原对白，不在句间切镜','composition':'方澄眼睛和嘴为中心，背景弱化但不改变人物或道具状态','visible':['C01_face','C01_mouth'],'dialogue_modes':['画内对白']},
 'lin_face_hand':{'camera':'前侧林屿面部中近景，脸和眼清晰，持笔右手在画面下沿可读','composition':'林屿面部停顿及看包回看纸的眼区为主，下沿保留原收笔动作','visible':['C02_face','pen'],'dialogue_modes':['无对白']},
 'documents_close':{'camera':'桌面斜俯近景，完整容纳明细单、结算单及林屿右手黑色签字笔','composition':'两份单据与右手笔同时可读；只跟随原文实际比对动作，不新增纸张反复移动','visible':['hands','documents','pen'],'dialogue_modes':['无对白']},
 'follow_fang':{'camera':'方澄前侧平视中景，轻跟从工位到门外的完整原动作；不添加起坐或关门','composition':'保留左肩挎包、右手电影票与自由左手推门的原分工，单镜连续，不重设初态','visible':['C01_face','bag','ticket','door'],'dialogue_modes':['无对白']},
 'corridor_face_ticket':{'camera':'走廊前侧三分之二面部中近景，面部、右手电影票与轻呼气同框清楚可读','composition':'面部和持票手同时入画，背景走廊弱化；不拍纯背影、不新增回头或对话','visible':['C01_face','ticket'],'dialogue_modes':['无对白']},
 'lin_table_medium':{'camera':'林屿工位前侧中近景，侧脸、右手黑色签字笔及两份单据同框','composition':'保持工作者与当前桌面物件同框，杯和便利贴作背景，不新增物件或动作','visible':['C02_face','hands','documents','pen'],'dialogue_modes':['无对白']},
}
ALLOWED={'B01':['office_wide'],'B02':['dual_front'],'B03':['table_hands'],'B04':['fang_face_pen'],'B05':['fang_face'],'B06':['lin_face_hand'],'B07':['documents_close'],'B08':['follow_fang'],'B09':['corridor_face_ticket'],'B10':['lin_table_medium','documents_close']}

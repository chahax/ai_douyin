import { app } from "/scripts/app.js";
import { ComfyWidgets } from "/scripts/widgets.js";

app.registerExtension({
    name: "ai_douyin.director.preview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "DouyinDirectorPreview") return;
        const original = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            original?.apply(this, arguments);
            if (!this.directorPreview) {
                this.directorPreview = ComfyWidgets.STRING(this, "待审输出", ["STRING", { multiline: true }], app).widget;
                this.directorPreview.inputEl.readOnly = true;
            }
            this.directorPreview.value = (message.text || []).join("\n\n");
            this.setDirtyCanvas(true, true);
        };
    },
});

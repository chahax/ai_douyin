from __future__ import annotations

import json
import pickle
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1" / "v2_debate"


def main() -> int:
    timeline = json.loads((OUT / "production_timeline.json").read_text(encoding="utf-8"))["timeline"]
    detector = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    report = []
    for item in timeline:
        sid = item["id"]
        image_path = OUT / "musetalk_plates" / f"{sid}.png"
        frame = cv2.imread(str(image_path))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(120, 120))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            pad_x = int(w * 0.08)
            x1 = max(0, x - pad_x)
            x2 = min(frame.shape[1], x + w + pad_x)
            y1 = max(0, y + int(h * 0.15))
            y2 = min(frame.shape[0], y + h + int(h * 0.10))
            method = "haar"
        else:
            # All production plates share a controlled chest-up composition.
            x1, y1, x2, y2 = 185, 205, 525, 630
            method = "fallback"
        coord = (int(x1), int(y1), int(x2), int(y2))
        with (OUT / f"{sid}.pkl").open("wb") as f:
            pickle.dump([coord], f)
        report.append({"id": sid, "coord": coord, "method": method})
        print(sid, coord, method)
    (OUT / "face_coords_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

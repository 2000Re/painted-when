"""冒頭の版(今の版 base / フック版 hook)ごとに、投稿した動画の一覧を出す。

YouTube Studio で各動画の「スワイプされずに視聴された割合」や「平均視聴率」を見て、版ごとに比べるときの対応表。
使い方: python tools/variants.py
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
history = json.loads((Path(__file__).resolve().parent.parent / "upload_history.json").read_text())
for variant in ("hook", "base"):
    rows = [h for h in history if (h.get("variant") or "base") == variant and h.get("variant")]
    print(f"\n== {variant}({'フック版' if variant == 'hook' else '今の版'}) {len(rows)}本")
    for h in rows:
        t = datetime.fromisoformat(h["uploaded_at"]).astimezone(JST).strftime("%m/%d %H:%M")
        print(f"  #{h['number']:<4} {t}  {h['source']:<3}  {h.get('artist') or '':<28} https://youtube.com/shorts/{h['video_id']}")
older = [h for h in history if not h.get("variant")]
if older:
    print(f"\n(比較を始める前の投稿 {len(older)}本は含めていない: #{older[0]['number']}〜#{older[-1]['number']})")

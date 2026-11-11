"""サイトのデータ(docs/data/quizzes.json)が始まる前に投稿したクイズを、美術館の API から取り直して足す。

選択肢は作品ごとに同じものが作られる(乱数のシードが「美術館:作品ID」)ので、動画と同じ3択になる。
念のため、投稿の記録の正解と一致するか確かめる。
使い方: python tools/backfill_site.py
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import art_shorts as A  # noqa: E402
import quiz as Q  # noqa: E402
import site_gen  # noqa: E402

history = json.loads((ROOT / "upload_history.json").read_text())
have = {x["number"] for x in site_gen.load()}
for h in history:
    if h["number"] in have:
        continue
    art = A.SOURCES[h["source"]]().fetch(h["id"])
    if not art:
        print(f"#{h['number']}: 作品を取得できません({h['key']})", file=sys.stderr)
        continue
    answer = Q.quiz_year(art)
    ys, correct = Q.make_choices(answer, random.Random(f"{art['source']}:{art['id']}"), int(h["date"][:4]))
    labels = Q.choice_labels(ys)
    if h.get("answer") and labels[correct] != h["answer"]:
        print(f"#{h['number']}: 正解が記録と違います({labels[correct]} / {h['answer']})", file=sys.stderr)
        continue
    art["quiz"] = {"choices": labels, "answer": correct}
    if h.get("artist"):
        art["famous_artist"] = h["artist"]   # 記録がない古い回は、site_fields が artists.py の名前に揃える
    meta = {"number": h["number"], "site": A.site_fields(art)}
    site_gen.add(site_gen.entry_from(meta, h["video_id"], h["uploaded_at"]))
    print(f"#{h['number']:<3} {labels} 正解 {labels[correct]}  {art['title'][:50]}")
site_gen.build()

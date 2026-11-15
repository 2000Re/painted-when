"""投稿した動画の再生数・高評価・コメント数を YouTube Data API から取り、stats.json と stats.md に残す。

4つのチャンネル(Painted When?、Guess From Space、Wait, That Big?、Too Close to Tell)で同じファイルを使う。
毎日 .github/workflows/daily-check.yml から動く。外部ライブラリなし(標準ライブラリのみ)。

- 必要な環境変数: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN(投稿と同じ。スコープ youtube.readonly で足りる)
- 動画は古いものほど再生が多いので、比べやすいよう、投稿から 1日・3日・7日たった時点の数字を固定して残す
  (毎日1回の実行なので、実際には「1日以上たって最初に測った値」。at に測った時刻、age_h に投稿からの時間。
  LATE_H 時間を過ぎてから測った値は残さないので、この仕組みより前の動画には最新の値しかない)
- stats.md には、upload_history.json の項目(版・カテゴリ・形式・美術館など)と投稿の時間帯ごとに、
  3日目の再生数の平均と中央値をまとめる(参考に、最新の再生数の平均も並べる)

使い方: python stats.py   (--dry-run で API を呼ばずに stats.md だけ作り直す)
"""
import argparse
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "upload_history.json"
STATS = ROOT / "stats.json"
REPORT = ROOT / "stats.md"
TOKEN_URL = "https://oauth2.googleapis.com/token"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
TZ = ZoneInfo("Asia/Tokyo")
MARKS = {"day1": 24, "day3": 72, "day7": 168}     # 名前: 投稿からの時間(h)
LATE_H = 36                                        # この時間を過ぎて測った値は、その時点の値としては残さない
COMPARE = "day3"                                   # 比べるのに使う時点
# 集計に使う upload_history.json の項目(あるものだけ使う)
GROUP_KEYS = ["title_style", "variant", "has_face", "source", "format", "category"]


def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def access_token():
    data = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    try:
        return http(TOKEN_URL, data=data)["access_token"]
    except urllib.error.HTTPError as e:
        raise SystemExit(f"アクセストークンを取れません (HTTP {e.code}): {e.read().decode(errors='replace')}")


def fetch(token, ids):
    """{video_id: {views, likes, comments}}。消えた動画は入らない。"""
    out = {}
    for i in range(0, len(ids), 50):
        q = urllib.parse.urlencode({"part": "statistics", "id": ",".join(ids[i:i + 50]), "maxResults": 50})
        res = http(f"{VIDEOS_URL}?{q}", headers={"Authorization": f"Bearer {token}"})
        for it in res.get("items", []):
            s = it.get("statistics", {})
            out[it["id"]] = {k: int(s.get(f, 0)) for k, f in
                             (("views", "viewCount"), ("likes", "likeCount"), ("comments", "commentCount"))}
    return out


def update(stats, history, current, now):
    for h in history:
        vid = h.get("video_id")
        if not vid:
            continue
        rec = stats.setdefault(str(h["number"]), {"video_id": vid})
        if vid not in current:
            rec["missing"] = True          # 削除・非公開化など
            continue
        rec.pop("missing", None)
        age = (now - datetime.fromisoformat(h["uploaded_at"])).total_seconds() / 3600
        snap = {**current[vid], "at": now.isoformat(timespec="seconds"), "age_h": round(age)}
        rec["latest"] = snap
        for name, hours in MARKS.items():
            # 遅れて測った値は比べられないので残さない(この仕組みより前の動画は、最新の値だけになる)
            if hours <= age < hours + LATE_H and name not in rec:
                rec[name] = snap
    return stats


def slot(h):
    """投稿の時間帯(日本時間の時)。"""
    return f"{datetime.fromisoformat(h['uploaded_at']).astimezone(TZ).hour:02d}時台"


def report(stats, history, now):
    rows = []
    for h in history:
        rec = stats.get(str(h["number"]), {})
        rows.append((h, rec))
    lines = [
        "# 再生数のまとめ",
        "",
        f"`stats.py` が毎日作り直す(最終更新 {now.astimezone(TZ):%Y-%m-%d %H:%M} JST)。"
        f"比べるのは投稿から約{MARKS[COMPARE] // 24}日目の再生数(古い動画ほど多くなるのをそろえるため)。"
        "「最新の平均」は投稿からの日数がそろっていないので参考。",
        "",
    ]

    def table(title, key_fn):
        groups = {}
        for h, rec in rows:
            g = groups.setdefault(key_fn(h), ([], []))
            if COMPARE in rec:
                g[0].append(rec[COMPARE]["views"])
            if "latest" in rec:
                g[1].append(rec["latest"]["views"])
        groups = {k: v for k, v in groups.items() if v[0] or v[1]}
        if not groups:
            return
        mean = lambda v: f"{statistics.mean(v):.0f}" if v else ""
        lines.extend([f"## {title}", "",
                      f"| 値 | {COMPARE[3:]}日目の本数 | 平均 | 中央値 | 最新の本数 | 最新の平均(参考) |",
                      "|---|---:|---:|---:|---:|---:|"])
        order = lambda kv: (-statistics.mean(kv[1][0]) if kv[1][0] else 0, -len(kv[1][1]))
        for k, (a, b) in sorted(groups.items(), key=order):
            med = f"{statistics.median(a):.0f}" if a else ""
            lines.append(f"| {k} | {len(a)} | {mean(a)} | {med} | {len(b)} | {mean(b)} |")
        lines.append("")

    table("全体", lambda h: "すべて")
    for key in GROUP_KEYS:
        if any(key in h for h, _ in rows):
            table(key, lambda h, key=key: h.get(key, "(なし)"))
    table("投稿の時間帯", slot)

    lines.extend(["## 動画ごと(新しい順)", "",
                  "| # | 答え | 投稿(JST) | 1日目 | 3日目 | 7日目 | 最新 | 高評価 | コメント |",
                  "|---:|---|---|---:|---:|---:|---:|---:|---:|"])
    for h, rec in reversed(rows):
        v = lambda name: str(rec[name]["views"]) if name in rec else ""
        last = rec.get("latest", {})
        when = datetime.fromisoformat(h["uploaded_at"]).astimezone(TZ).strftime("%m-%d %H:%M")
        answer = str(h.get("answer", "")).replace("|", "/")
        url = f"https://youtube.com/shorts/{h['video_id']}" if h.get("video_id") else ""
        num = f"[{h['number']}]({url})" if url else str(h["number"])
        flag = " (見られない)" if rec.get("missing") else ""
        lines.append(f"| {num} | {answer}{flag} | {when} | {v('day1')} | {v('day3')} | {v('day7')} | "
                     f"{last.get('views', '')} | {last.get('likes', '')} | {last.get('comments', '')} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="API を呼ばず、stats.md だけ作り直す")
    args = ap.parse_args()
    history = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    stats = json.loads(STATS.read_text()) if STATS.exists() else {}
    now = datetime.now(timezone.utc)
    if not args.dry_run:
        ids = [h["video_id"] for h in history if h.get("video_id")]
        current = fetch(access_token(), ids) if ids else {}
        update(stats, history, current, now)
        STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        print(f"{len(current)}/{len(ids)} 本の数字を取りました")
    text = report(stats, history, now)
    REPORT.write_text(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text)


if __name__ == "__main__":
    sys.exit(main())

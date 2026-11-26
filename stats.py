"""投稿した動画の再生数・高評価・コメント数を YouTube Data API から取り、stats.json と stats.md に残す。

4つのチャンネル(Painted When?、Guess From Space、Wait, That Big?、Too Close to Tell)で同じファイルを使う。
毎日 .github/workflows/daily-check.yml から動く。外部ライブラリなし(標準ライブラリのみ)。

- 必要な環境変数: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN(投稿と同じ。スコープ youtube.readonly で足りる)
- 動画は古いものほど再生が多いので、比べやすいよう、投稿から 1日・3日・7日たった時点の数字を固定して残す
  (毎日1回の実行なので、実際には「1日以上たって最初に測った値」。at に測った時刻、age_h に投稿からの時間。
  LATE_H 時間を過ぎてから測った値は残さないので、この仕組みより前の動画には最新の値しかない)
- stats.md には、upload_history.json の項目(版・カテゴリ・形式・美術館など)と投稿の時間帯ごとに、
  3日目の再生数の平均と中央値をまとめる(参考に、最新の再生数の平均も並べる)

- YouTube Analytics API(スコープ yt-analytics.readonly)も使えれば、動画ごとの平均視聴割合・登録者の増加と、
  チャンネルの日別の流入元(ショート フィードからの再生の割合)も記録する。Analytics の数字は2〜3日遅れて出る。
  トークンにこのスコープがない(get_youtube_refresh_token.py で取り直す前の)ときは、その部分だけ飛ばす

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
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
TRAFFIC_DAYS = 28                                  # 流入元の表に出す日数
TZ = ZoneInfo("Asia/Tokyo")
MARKS = {"day1": 24, "day3": 72, "day7": 168}     # 名前: 投稿からの時間(h)
LATE_H = 36                                        # この時間を過ぎて測った値は、その時点の値としては残さない
COMPARE = "day3"                                   # 比べるのに使う時点
# 集計に使う upload_history.json の項目(あるものだけ使う)
GROUP_KEYS = ["title_style", "variant", "has_face", "source", "format", "category", "ending"]


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


def analytics_query(token, **params):
    """YouTube Analytics API の reports。[{列名: 値}] を返す。"""
    q = urllib.parse.urlencode({"ids": "channel==MINE", **params})
    res = http(f"{ANALYTICS_URL}?{q}", headers={"Authorization": f"Bearer {token}"})
    cols = [c["name"] for c in res.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in res.get("rows", [])]


def fetch_analytics(token, history, now):
    """(動画ごとの数字 {video_id: {...}}, 日別の流入元 {日付: {流入元: 再生数}}, 説明)。使えなければ空と理由。"""
    if not history:
        return {}, {}, ""
    first = min(datetime.fromisoformat(h["uploaded_at"]) for h in history).astimezone(TZ).date()
    today = now.astimezone(TZ).date()
    per_video, traffic, notes = {}, {}, []
    try:
        for metrics in ("views,averageViewPercentage,averageViewDuration,subscribersGained",
                        "views,averageViewDuration,subscribersGained"):
            try:
                rows = analytics_query(token, startDate=first.isoformat(), endDate=today.isoformat(),
                                       metrics=metrics, dimensions="video", sort="-views", maxResults=200)
                break
            except urllib.error.HTTPError as e:
                if e.code != 400 or "averageViewPercentage" not in metrics:
                    raise
                notes.append("平均視聴割合は取れなかった(この組み合わせは API が受け付けない)")
        for r in rows:
            per_video[r["video"]] = {k: r[k] for k in r if k != "video"}
        start = datetime.fromtimestamp(now.timestamp() - TRAFFIC_DAYS * 86400, TZ).date()
        for r in analytics_query(token, startDate=start.isoformat(), endDate=today.isoformat(), metrics="views",
                                 dimensions="day,insightTrafficSourceType", sort="day"):
            traffic.setdefault(r["day"], {})[r["insightTrafficSourceType"]] = r["views"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        if e.code in (401, 403):
            return {}, {}, ("YouTube Analytics の数字は取っていない(トークンに yt-analytics.readonly のスコープがないか、"
                            "YouTube Analytics API が有効になっていない)")
        return per_video, traffic, f"YouTube Analytics の取得に失敗 (HTTP {e.code}): {detail}"
    return per_video, traffic, " / ".join(notes)


COUNTRY_TOP = 10          # チャンネル全体で並べる国の数
COUNTRY_VIDEOS = 8        # 国の内訳を取る動画の数(再生の多い順。API の呼び出しを増やしすぎないため)
COUNTRY_NAMES = {
    "US": "アメリカ", "JP": "日本", "IN": "インド", "GB": "イギリス", "CA": "カナダ", "AU": "オーストラリア",
    "DE": "ドイツ", "FR": "フランス", "BR": "ブラジル", "MX": "メキシコ", "ES": "スペイン", "IT": "イタリア",
    "PH": "フィリピン", "ID": "インドネシア", "VN": "ベトナム", "PK": "パキスタン", "BD": "バングラデシュ",
    "NG": "ナイジェリア", "TR": "トルコ", "RU": "ロシア", "PL": "ポーランド", "NL": "オランダ", "AR": "アルゼンチン",
    "CO": "コロンビア", "PE": "ペルー", "CL": "チリ", "KR": "韓国", "TW": "台湾", "TH": "タイ", "MY": "マレーシア",
    "SA": "サウジアラビア", "EG": "エジプト", "ZA": "南アフリカ", "NZ": "ニュージーランド", "SE": "スウェーデン",
    "PT": "ポルトガル", "UA": "ウクライナ", "IE": "アイルランド", "SG": "シンガポール", "KE": "ケニア",
}


def fetch_countries(token, history, stats, now):
    """視聴者の国の内訳。{"channel": {国: 再生数}, "videos": {回の番号: {国: 再生数}}, "days": 日数}。
    チャンネル全体は直近 TRAFFIC_DAYS 日。動画ごとは、再生の多い COUNTRY_VIDEOS 本だけ(投稿からの全期間)。"""
    today = now.astimezone(TZ).date()
    start = datetime.fromtimestamp(now.timestamp() - TRAFFIC_DAYS * 86400, TZ).date()
    out = {"channel": {}, "videos": {}, "days": TRAFFIC_DAYS}
    for r in analytics_query(token, startDate=start.isoformat(), endDate=today.isoformat(), metrics="views",
                             dimensions="country", sort="-views", maxResults=COUNTRY_TOP):
        out["channel"][r["country"]] = r["views"]
    views = lambda h: (stats.get(str(h["number"]), {}).get("latest") or {}).get("views", 0)
    top = sorted([h for h in history if h.get("video_id")], key=views, reverse=True)[:COUNTRY_VIDEOS]
    for h in top:
        first = datetime.fromisoformat(h["uploaded_at"]).astimezone(TZ).date()
        rows = analytics_query(token, startDate=first.isoformat(), endDate=today.isoformat(), metrics="views",
                               dimensions="country", filters=f"video=={h['video_id']}", sort="-views", maxResults=5)
        out["videos"][str(h["number"])] = {r["country"]: r["views"] for r in rows}
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
            g = groups.setdefault(key_fn(h), ([], [], []))
            if COMPARE in rec:
                g[0].append(rec[COMPARE]["views"])
            if "latest" in rec:
                g[1].append(rec["latest"]["views"])
            if "averageViewPercentage" in rec.get("analytics", {}):
                g[2].append(rec["analytics"]["averageViewPercentage"])
        groups = {k: v for k, v in groups.items() if v[0] or v[1]}
        if not groups:
            return
        mean = lambda v: f"{statistics.mean(v):.0f}" if v else ""
        lines.extend([f"## {title}", "",
                      f"| 値 | {COMPARE[3:]}日目の本数 | 平均 | 中央値 | 最新の本数 | 最新の平均(参考) | 平均視聴割合(%) |",
                      "|---|---:|---:|---:|---:|---:|---:|"])
        order = lambda kv: (-statistics.mean(kv[1][0]) if kv[1][0] else 0, -len(kv[1][1]))
        for k, (a, b, c) in sorted(groups.items(), key=order):
            med = f"{statistics.median(a):.0f}" if a else ""
            lines.append(f"| {k} | {len(a)} | {mean(a)} | {med} | {len(b)} | {mean(b)} | {mean(c)} |")
        lines.append("")

    table("全体", lambda h: "すべて")
    for key in GROUP_KEYS:
        if any(key in h for h, _ in rows):
            table(key, lambda h, key=key: h.get(key, "(なし)"))
    table("投稿の時間帯", slot)

    traffic = stats.get("_traffic") or {}
    if traffic:
        lines.extend([f"## 日別の再生と流入元(直近{TRAFFIC_DAYS}日、YouTube Analytics。2〜3日遅れ)", "",
                      "| 日付 | 再生(全体) | ショート フィード | 割合 |", "|---|---:|---:|---:|"])
        for day in sorted(traffic, reverse=True):
            src = traffic[day]
            total = sum(src.values())
            sf = src.get("SHORTS", 0)
            lines.append(f"| {day} | {total} | {sf} | {sf / total * 100:.0f}% |" if total else f"| {day} | 0 | 0 | |")
        lines.append("")
    countries = stats.get("_countries") or {}
    if countries.get("channel"):
        name = lambda c: f"{COUNTRY_NAMES.get(c, c)}"
        total = sum(countries["channel"].values())
        lines.extend([f"## 視聴者の国(直近{countries.get('days', TRAFFIC_DAYS)}日、上位{COUNTRY_TOP}か国。YouTube Analytics)", "",
                      "| 国 | 再生 | 上位の中の割合 |", "|---|---:|---:|"])
        for c, v in countries["channel"].items():
            lines.append(f"| {name(c)} ({c}) | {v} | {v / total * 100:.0f}% |" if total else f"| {name(c)} | {v} | |")
        lines.append("")
        if countries.get("videos"):
            by_num = {str(h["number"]): h for h in history}
            lines.extend([f"## 再生の多い動画の国(上位5か国、投稿からの全期間)", "",
                          "| # | 答え | 国の内訳 |", "|---:|---|---|"])
            for num, cs in sorted(countries["videos"].items(), key=lambda kv: -sum(kv[1].values())):
                t = sum(cs.values())
                parts = ", ".join(f"{name(c)} {v / t * 100:.0f}%" for c, v in cs.items()) if t else ""
                ans = str(by_num.get(num, {}).get("answer", "")).replace("|", "/")[:60]
                lines.append(f"| {num} | {ans} | {parts} |")
            lines.append("")
    if stats.get("_analytics_note"):
        lines.extend([f"(Analytics: {stats['_analytics_note']})", ""])

    lines.extend(["## 動画ごと(新しい順)", "",
                  "| # | 答え | 投稿(JST) | 1日目 | 3日目 | 7日目 | 最新 | 高評価 | コメント | 平均視聴割合 | 登録者+ |",
                  "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for h, rec in reversed(rows):
        v = lambda name: str(rec[name]["views"]) if name in rec else ""
        last = rec.get("latest", {})
        when = datetime.fromisoformat(h["uploaded_at"]).astimezone(TZ).strftime("%m-%d %H:%M")
        answer = str(h.get("answer", "")).replace("|", "/")
        url = f"https://youtube.com/shorts/{h['video_id']}" if h.get("video_id") else ""
        num = f"[{h['number']}]({url})" if url else str(h["number"])
        flag = " (見られない)" if rec.get("missing") else ""
        an = rec.get("analytics", {})
        avp = f"{an['averageViewPercentage']:.0f}%" if "averageViewPercentage" in an else ""
        lines.append(f"| {num} | {answer}{flag} | {when} | {v('day1')} | {v('day3')} | {v('day7')} | "
                     f"{last.get('views', '')} | {last.get('likes', '')} | {last.get('comments', '')} | "
                     f"{avp} | {an.get('subscribersGained', '')} |")
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
        token = access_token()
        current = fetch(token, ids) if ids else {}
        update(stats, history, current, now)
        per_video, traffic, note = fetch_analytics(token, history, now)
        for h in history:
            if h.get("video_id") in per_video:
                stats.setdefault(str(h["number"]), {})["analytics"] = {**per_video[h["video_id"]],
                                                                        "at": now.isoformat(timespec="seconds")}
        if traffic:
            stats["_traffic"] = traffic
        if per_video:                          # Analytics が使えるときだけ(国の内訳。失敗しても他は残す)
            try:
                stats["_countries"] = fetch_countries(token, history, stats, now)
            except Exception as e:  # noqa: BLE001
                note = (note + " / " if note else "") + f"国の内訳を取れなかった ({e})"
        stats["_analytics_note"] = note
        print(f"Analytics: 動画 {len(per_video)} 本、流入元 {len(traffic)} 日分" + (f"({note})" if note else ""))
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

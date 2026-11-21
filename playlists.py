"""投稿した動画を、合う再生リストへ自動で入れる(4チャンネル共通。標準ライブラリだけ)。

どの動画をどの再生リストに入れるかは、各リポジトリの playlist_rules.py の for_record(記録) が決める
(返り値は [(再生リストの題名, 説明)])。再生リストがまだなければ、公開で作る。題名が同じものがあれば、それを使う。

- 投稿のあと youtube_upload.py(と Wait, That Big? の longform.py)から add_after_upload() を呼ぶ。
  失敗しても投稿は止めない(警告を出すだけ)
- 再生リストを操作するには、リフレッシュトークンに youtube スコープが要る(get_youtube_refresh_token.py)。
  足りなければ「権限がない」と1回だけ表示して何もしない
- これまでの動画をまとめて入れる: python playlists.py --backfill(.github/workflows/playlists.yml から手動で動かす)。
  すでに入っている動画は入れ直さない

使う枠(1日 10,000): 一覧 1、作成 50、追加 50。
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path

PLAYLISTS_URL = "https://www.googleapis.com/youtube/v3/playlists"
ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"


class NoPermission(Exception):
    pass


def _call(token, url, body=None, method=None):
    import youtube_upload as Y
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json; charset=UTF-8"
        data = json.dumps(body).encode()
    try:
        _, _, res = Y.request(url, data=data, headers=headers, method=method)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        if e.code in (401, 403) and ("insufficient" in detail.lower() or "ACCESS_TOKEN_SCOPE" in detail):
            raise NoPermission(detail[:300]) from e
        raise RuntimeError(f"HTTP {e.code}: {detail[:300]}") from e
    return json.loads(res or b"{}")


class Playlists:
    def __init__(self, token):
        self.token = token
        self.ids = None            # 題名 → ID
        self.members = {}          # ID → 入っている動画 ID の集合

    def _load(self):
        self.ids, page = {}, None
        while True:
            q = {"part": "snippet", "mine": "true", "maxResults": 50}
            if page:
                q["pageToken"] = page
            res = _call(self.token, f"{PLAYLISTS_URL}?{urllib.parse.urlencode(q)}")
            for it in res.get("items", []):
                self.ids.setdefault(it["snippet"]["title"], it["id"])
            page = res.get("nextPageToken")
            if not page:
                break

    def get(self, title, description):
        if self.ids is None:
            self._load()
        if title not in self.ids:
            res = _call(self.token, f"{PLAYLISTS_URL}?part=snippet,status", {
                "snippet": {"title": title, "description": description, "defaultLanguage": "en"},
                "status": {"privacyStatus": "public"},
            }, method="POST")
            self.ids[title] = res["id"]
            self.members[res["id"]] = set()
            print(f"再生リストを作りました: {title}")
        return self.ids[title]

    def videos(self, pid):
        if pid not in self.members:
            vids, page = set(), None
            while True:
                q = {"part": "contentDetails", "playlistId": pid, "maxResults": 50}
                if page:
                    q["pageToken"] = page
                res = _call(self.token, f"{ITEMS_URL}?{urllib.parse.urlencode(q)}")
                vids |= {it["contentDetails"]["videoId"] for it in res.get("items", [])}
                page = res.get("nextPageToken")
                if not page:
                    break
            self.members[pid] = vids
        return self.members[pid]

    def add(self, video_id, lists):
        """lists: [(題名, 説明)]。入れた再生リストの題名を返す。"""
        added = []
        for title, desc in lists:
            pid = self.get(title, desc)
            if video_id in self.videos(pid):
                continue
            _call(self.token, f"{ITEMS_URL}?part=snippet", {
                "snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": video_id}},
            }, method="POST")
            self.members[pid].add(video_id)
            added.append(title)
        return added


NO_PERMISSION = ("警告: 再生リストを操作する権限がトークンにありません。get_youtube_refresh_token.py で"
                 "リフレッシュトークンを取り直してください(README の「再生リスト」)。投稿はできています")


def add_after_upload(token, record):
    """投稿のあとに呼ぶ。record は投稿記録の1件(video_id を含む)。失敗しても例外は出さない。"""
    try:
        import playlist_rules
        lists = playlist_rules.for_record(record)
        if not lists:
            return
        added = Playlists(token).add(record["video_id"], lists)
        for t in added:
            print(f"再生リストに追加: {t}")
    except NoPermission:
        print(NO_PERMISSION, file=sys.stderr)
    except Exception as e:
        print(f"警告: 再生リストに追加できませんでした: {e}", file=sys.stderr)


def backfill():
    import playlist_rules
    import youtube_upload as Y
    token = Y.connect()
    pl = Playlists(token)
    n = 0
    try:
        for path in playlist_rules.HISTORIES:
            p = Path(__file__).resolve().parent / path
            if not p.exists():
                continue
            for rec in json.loads(p.read_text() or "[]"):
                if not rec.get("video_id"):
                    continue
                try:
                    added = pl.add(rec["video_id"], playlist_rules.for_record(rec))
                except RuntimeError as e:          # 消した動画など。その回だけ飛ばして続ける
                    print(f"#{rec.get('number')} ({rec['video_id']}): 入れられません: {e}", file=sys.stderr)
                    continue
                for t in added:
                    print(f"#{rec.get('number')} → {t}")
                    n += 1
    except NoPermission:
        raise SystemExit(NO_PERMISSION)
    print(f"追加: {n} 件")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="投稿記録にあるこれまでの動画を、まとめて再生リストに入れる")
    ap.add_argument("--show", action="store_true", help="投稿記録の各回が、どの再生リストに入るかを表示するだけ(通信なし)")
    args = ap.parse_args()
    if args.backfill:
        backfill()
    elif args.show:
        import playlist_rules
        for path in playlist_rules.HISTORIES:
            p = Path(__file__).resolve().parent / path
            for rec in json.loads(p.read_text() or "[]") if p.exists() else []:
                print(f"#{rec.get('number')} {path}: {[t for t, _ in playlist_rules.for_record(rec)]}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()

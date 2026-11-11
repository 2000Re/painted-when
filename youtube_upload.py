"""art_shorts.py の出力(out/meta.json と、そこに書かれた動画)を YouTube にアップロードし、
upload_history.json に記録する。

外部ライブラリに依存しない(標準ライブラリの urllib のみ)。
必要な環境変数: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
任意: YT_CHANNEL_ID … 設定すると、アップロード先のチャンネルが違うときに中止する(別チャンネルへの誤投稿防止)

終了コード: 0 成功 / 1 その他の失敗 / 2 Secrets が未設定 / 3 リフレッシュトークンが無効(再取得が必要)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_ENV = ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
CATEGORY_EDUCATION = "27"


class TokenInvalid(Exception):
    pass


def set_output(name, value):
    """GitHub Actions のステップ出力に書く(ローカル実行時は何もしない)。"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{name}={value}\n")


def request(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=300) as res:
        return res.status, dict(res.headers), res.read()


def get_access_token():
    data = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    try:
        _, _, body = request(TOKEN_URL, data=data)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        if "invalid_grant" in detail or "invalid_client" in detail:
            raise TokenInvalid(detail) from e
        raise RuntimeError(f"アクセストークンの取得に失敗しました (HTTP {e.code}): {detail}") from e
    return json.loads(body)["access_token"]


def check_channel(token, expected):
    _, _, body = request(CHANNELS_URL, headers={"Authorization": f"Bearer {token}"})
    items = json.loads(body).get("items", [])
    actual = items[0]["id"] if items else None
    if actual != expected:
        name = items[0]["snippet"]["title"] if items else "(なし)"
        raise SystemExit(f"アップロード先のチャンネルが違います: {name} ({actual}) / 期待値 {expected}")
    print(f"channel ok: {items[0]['snippet']['title']}")


def upload(token, video_path, meta, privacy):
    body = json.dumps({
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": CATEGORY_EDUCATION,
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }).encode()
    size = video_path.stat().st_size
    _, headers, _ = request(UPLOAD_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(size),
    })
    location = headers.get("Location") or headers.get("location")
    # 動画は数MBなので一括 PUT。5xx・通信断のときだけ再試行する
    for attempt in range(4):
        try:
            _, _, res = request(location, data=video_path.read_bytes(), method="PUT", headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "video/mp4",
            })
            return json.loads(res)
        except (urllib.error.URLError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code < 500:
                raise
            wait = 2 ** (attempt + 1)
            print(f"upload failed ({e}), retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("アップロードに4回失敗しました")


def connect():
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        print(f"GitHub Secrets が未設定です: {', '.join(missing)}(README の自動投稿のセットアップ)", file=sys.stderr)
        sys.exit(2)
    try:
        token = get_access_token()
    except TokenInvalid as e:
        print(f"リフレッシュトークンが無効です。README の手順で再取得してください。\n{e}", file=sys.stderr)
        set_output("token_invalid", "true")
        sys.exit(3)
    if os.environ.get("YT_CHANNEL_ID"):
        check_channel(token, os.environ["YT_CHANNEL_ID"])
    return token


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="out")
    ap.add_argument("--history", default=str(Path(__file__).parent / "upload_history.json"))
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    args = ap.parse_args()

    out = Path(args.dir)
    meta = json.loads((out / "meta.json").read_text())
    history_path = Path(args.history)
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    if any(h["key"] == meta["key"] for h in history):
        raise SystemExit(f"投稿済みの作品です: {meta['key']}")

    token = connect()
    res = upload(token, out / meta["video"], meta, args.privacy)
    video_id = res["id"]
    actual_privacy = res.get("status", {}).get("privacyStatus", args.privacy)
    print(f"uploaded: https://youtube.com/shorts/{video_id} ({actual_privacy})")
    if actual_privacy != args.privacy:
        # 未審査の API プロジェクトからのアップロードは、YouTube 側で非公開に固定される
        print(f"警告: 公開設定 {args.privacy} を指定しましたが、{actual_privacy} になりました"
              "(API プロジェクトが未審査の可能性があります。README 参照)", file=sys.stderr)
    set_output("video_id", video_id)

    history.append({
        "number": meta["number"],
        "key": meta["key"],
        "source": meta["source"],
        "id": meta["id"],
        "date": meta["date"],
        "title": meta["title"],
        "answer": meta["answer"],
        "artist": meta.get("artist"),
        "variant": meta.get("variant"),
        "has_face": meta.get("has_face"),
        "video_id": video_id,
        "privacy": actual_privacy,
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n")

    # サイト(docs/)にクイズのページを足す。失敗しても投稿の記録は残す(記録がないと同じ作品をまた選んでしまう)
    if meta.get("site"):
        try:
            import site_gen
            site_gen.add(site_gen.entry_from(meta, video_id, history[-1]["uploaded_at"]))
            site_gen.build()
        except Exception as e:
            print(f"警告: サイトのページを作れませんでした: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()

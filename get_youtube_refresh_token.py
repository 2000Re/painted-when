"""新チャンネル用のリフレッシュトークンを取得する(ローカルPCで一度だけ実行)。

事前準備(詳しくは README):
  1. Google Cloud Console で YouTube Data API v3 を有効化
  2. OAuth同意画面を作成し、公開ステータスを「本番環境」にする
     (「テスト」のままだとリフレッシュトークンが7日で失効する)
  3. OAuthクライアントID(種類: デスクトップアプリ)を作成し、JSONをダウンロード

使い方:
  pip install google-auth-oauthlib
  python3 get_youtube_refresh_token.py client_secret_xxx.json

ブラウザが開いたら、アカウント選択で必ず Painted When? のチャンネル(@painted-when)を選ぶ。
最後に表示される値を GitHub Secrets に登録する。
"""
import json
import sys
import urllib.request

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # 投稿先チャンネルの確認用
]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    # prompt=consent を付けないと、2回目以降はリフレッシュトークンが返らないことがある
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    req = urllib.request.Request(
        "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
        headers={"Authorization": f"Bearer {creds.token}"})
    items = json.loads(urllib.request.urlopen(req).read()).get("items", [])
    if not items:
        sys.exit("このアカウントにはYouTubeチャンネルがありません。アカウント選択をやり直してください。")
    channel = items[0]

    print("\n認証したチャンネル:", channel["snippet"]["title"])
    print("※ Painted When? 以外のチャンネルになっていたら、選ぶアカウントが違います。やり直してください。\n")
    print("GitHub Secrets に登録する値:")
    print(f"  YT_CLIENT_ID      = {creds.client_id}")
    print(f"  YT_CLIENT_SECRET  = {creds.client_secret}")
    print(f"  YT_REFRESH_TOKEN  = {creds.refresh_token}")
    print(f"  YT_CHANNEL_ID     = {channel['id']}")


if __name__ == "__main__":
    main()

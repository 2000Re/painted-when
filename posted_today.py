"""直近に投稿済みかを調べ、GitHub Actions のステップ出力 skip=true/false を書く。

定期実行は本命と予備の2回起動する(.github/workflows/post.yml)。
GitHub の定期実行は数時間遅れて日付をまたぐことがあるので、「今日の日付に投稿があるか」ではなく
「最後の投稿から RECENT_HOURS 時間以内か」で判定する。
(日付で判定すると、深夜に遅れて動いた予備の回が翌日分として数えられ、
 翌日の本命の回が毎日スキップされてしまう。ねこピアノで 2026-10 に実際に発生)
手動実行ではこのチェックは使わない。
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

RECENT_HOURS = 12
HISTORY = Path(__file__).parent / "upload_history.json"


def posted_recently(history, now=None, hours=RECENT_HOURS):
    now = now or datetime.now(timezone.utc)
    return any(now - datetime.fromisoformat(h["uploaded_at"]) < timedelta(hours=hours) for h in history)


def main():
    history = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    skip = posted_recently(history)
    print(f"直近{RECENT_HOURS}時間以内に投稿済みなのでスキップします" if skip else "直近に投稿はありません")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"skip={'true' if skip else 'false'}\n")


if __name__ == "__main__":
    main()

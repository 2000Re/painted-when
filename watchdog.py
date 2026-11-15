"""投稿が止まっていないかを調べ、GitHub Actions のステップ出力 stalled=true/false と hours を書く。

post.yml の失敗は post.yml 自身が Issue にするが、cron-job.org のトークン切れなどで「起動されなかった」ときは
何も残らない。そこで毎日 .github/workflows/daily-check.yml から、最後の投稿から STALL_HOURS 時間以上たっていないかを見る。
リポジトリ変数 AUTO_POST が true でない(定期投稿を止めている)ときは調べない。

4つのチャンネルで同じファイルを使う。
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

STALL_HOURS = 30        # 1日2本なら、ふだんの間隔はいちばん長くても20時間ほど
HISTORY = Path(__file__).resolve().parent / "upload_history.json"


def check(history, auto_post, now=None):
    """(止まっているか, 最後の投稿からの時間 or None, 説明)。"""
    now = now or datetime.now(timezone.utc)
    if auto_post != "true":
        return False, None, "AUTO_POST が true ではないので調べません"
    if not history:
        return False, None, "まだ投稿がありません"
    last = max(datetime.fromisoformat(h["uploaded_at"]) for h in history)
    hours = (now - last).total_seconds() / 3600
    if hours >= STALL_HOURS:
        return True, hours, f"最後の投稿から {hours:.0f} 時間たっています(基準 {STALL_HOURS} 時間)"
    return False, hours, f"最後の投稿から {hours:.0f} 時間(正常)"


def main():
    history = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    stalled, hours, msg = check(history, os.environ.get("AUTO_POST", ""))
    print(msg)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"stalled={'true' if stalled else 'false'}\n")
            f.write(f"message={msg}\n")


if __name__ == "__main__":
    main()

"""定期実行で、今回投稿してよいかを調べ、GitHub Actions のステップ出力 skip=true/false を書く。

1日(日本時間)に MAX_PER_DAY 本まで投稿する。本命は cron-job.org の 07:17・10:17・22:17 の起動。
次のどれかに当たればスキップする:
  - 今日(日本時間)すでに MAX_PER_DAY 本投稿している
  - 最後の投稿から MIN_GAP_HOURS 時間たっていない(同じ時間帯に起動が重なったときの二重投稿を防ぐ)
  - GitHub 自身の定期実行(予備。09:17 の予定が数時間遅れることがある)で、今日すでに1本以上投稿している。
    予備は cron-job.org が止まった日の保険なので、本命の時間帯を先取りしないようにする
手動実行ではこのチェックは使わない。
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

MAX_PER_DAY = 3
MIN_GAP_HOURS = 1.5
TZ = ZoneInfo("Asia/Tokyo")
HISTORY = Path(__file__).parent / "upload_history.json"


def should_skip(history, now=None, backup=False):
    """(スキップするか, 理由) を返す。backup=True は GitHub 自身の定期実行(予備)。"""
    now = now or datetime.now(timezone.utc)
    times = [datetime.fromisoformat(h["uploaded_at"]) for h in history]
    today = now.astimezone(TZ).date()
    n_today = sum(1 for t in times if t.astimezone(TZ).date() == today)
    if n_today >= MAX_PER_DAY:
        return True, f"今日(日本時間)はすでに{n_today}本投稿しています(上限{MAX_PER_DAY}本)"
    if backup and n_today >= 1:
        return True, f"予備の起動です。今日はすでに{n_today}本投稿しているので、本命の起動に任せます"
    if times and now - max(times) < timedelta(hours=MIN_GAP_HOURS):
        return True, f"最後の投稿から{MIN_GAP_HOURS}時間たっていません"
    return False, f"投稿します(今日{n_today + 1}本目)"


def main():
    history = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    skip, reason = should_skip(history, backup=os.environ.get("EVENT") == "schedule")
    print(reason)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"skip={'true' if skip else 'false'}\n")


if __name__ == "__main__":
    main()

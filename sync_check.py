"""4つのチャンネルのリポジトリで、共通のファイルがずれていないかを調べる。

Painted When?、Guess From Space、Wait, That Big?、Too Close to Tell は、仕組みが同じなので
同じ(または、ほぼ同じ)ファイルをそれぞれ持っている。1つで直した不具合を、ほかで直し忘れないための確認。

- SAME: 4つで完全に同じであるべきファイル。違えば「ずれ」として報告する(終了コード 1)
- SIMILAR: チャンネルごとに少し違ってよいファイル(チャンネル名、記録する項目など)。
  基準(painted-when)と違う行数を並べるだけ。--diff で中身を見る

各リポジトリの main を raw.githubusercontent.com から読む(公開リポジトリなのでキーはいらない)。
標準ライブラリだけ。毎日 daily-check.yml でも動き、結果を Actions の画面(Summary)に出す。

使い方:
  python sync_check.py                         # 一覧
  python sync_check.py --diff youtube_upload.py # そのファイルの、基準との差分
"""
import argparse
import difflib
import os
import re
import sys
import urllib.error
import urllib.request

OWNER = "2000Re"
REPOS = ["painted-when", "guess-from-space", "wait-that-big", "too-close-to-tell"]
SAME = ["stats.py", "watchdog.py", "sync_check.py", ".github/workflows/daily-check.yml", "playlists.py",
        ".github/workflows/playlists.yml"]
SIMILAR = ["youtube_upload.py", "posted_today.py", "get_youtube_refresh_token.py", "site_gen.py",
           ".github/workflows/post.yml"]


def normalize(path, text):
    """リポジトリごとに違ってよい部分をそろえる(daily-check.yml の起動時刻)。"""
    if path.endswith("daily-check.yml"):
        text = re.sub(r'cron: "[^"]*"', 'cron: "*"', text)
    return text


def fetch(repo, path):
    url = f"https://raw.githubusercontent.com/{OWNER}/{repo}/main/{path}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "sync-check"}),
                                    timeout=30) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def changed_lines(a, b):
    return sum(1 for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
               if l[:1] in "+-" and not l.startswith(("+++", "---")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", metavar="PATH", help="このファイルの、基準(painted-when)と各リポジトリの差分を出す")
    args = ap.parse_args()

    if args.diff:
        base = fetch(REPOS[0], args.diff) or ""
        for repo in REPOS[1:]:
            other = fetch(repo, args.diff) or ""
            sys.stdout.writelines(difflib.unified_diff(
                base.splitlines(True), other.splitlines(True), f"{REPOS[0]}/{args.diff}", f"{repo}/{args.diff}"))
        return 0

    lines = ["# 共通ファイルのずれ", "",
             f"基準は {REPOS[0]}。数字は基準と違う行数(— はファイルがない)。", "",
             "| ファイル | 種類 | " + " | ".join(REPOS) + " |",
             "|---|---|" + "---:|" * len(REPOS)]
    drift = []
    for kind, paths in (("同じであるべき", SAME), ("似ている", SIMILAR)):
        for path in paths:
            texts = {r: fetch(r, path) for r in REPOS}
            base = texts[REPOS[0]]
            cells = []
            for r in REPOS:
                t = texts[r]
                if t is None:
                    cells.append("—")
                    if kind == "同じであるべき":
                        drift.append(f"{r} に {path} がない")
                    continue
                n = changed_lines(normalize(path, base or ""), normalize(path, t))
                cells.append(str(n) if r != REPOS[0] else "基準")
                if kind == "同じであるべき" and n:
                    drift.append(f"{r} の {path} が基準と {n} 行違う")
            lines.append(f"| `{path}` | {kind} | " + " | ".join(cells) + " |")
    lines.append("")
    if drift:
        lines += ["**ずれ:**", ""] + [f"- {d}" for d in drift] + [
            "", "どれか1つを直したら、ほかの3つにも同じファイルをコピーする。"]
    else:
        lines.append("同じであるべきファイルは、4つとも同じ。")
    text = "\n".join(lines) + "\n"
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text)
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())

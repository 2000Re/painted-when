"""Painted When? のサイト(GitHub Pages、docs/)に、クイズの一覧ページと作品ごとのページを作る。

データは docs/data/quizzes.json(投稿のたびに youtube_upload.py が1件足す)。そこから次を作り直す:
  docs/quiz/<番号>-<作品名>/index.html  作品ごとのページ(動画・3択・「答えを見る」・作品の情報)
  docs/quiz/index.html                  全問の一覧(新しい順)
  docs/index.html                       トップの「最新のクイズ」(<!-- LATEST:START --> 〜 END の間だけ書き換える)
  docs/sitemap.xml                      検索エンジン向けのページ一覧

画像はリポジトリに保存せず、美術館の画像配信(Met の primaryImageSmall、シカゴ美術館の IIIF)から表示する。
GitHub Actions の upload ジョブ(外部ライブラリなし)から使うので、標準ライブラリだけで書く。

使い方: python site_gen.py   (docs/data/quizzes.json からページを作り直す)
"""
import html
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
DATA = DOCS / "data" / "quizzes.json"
SITE = "https://2000re.github.io/painted-when"
CHANNEL = "https://www.youtube.com/@painted-when"
LATEST = 12

e = html.escape


def slugify(text, limit=60):
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:limit].rstrip("-") or "painting"


def entry_from(meta, video_id, uploaded_at):
    """youtube_upload.py の meta.json とアップロード結果から、サイト用の1件を作る。"""
    s = meta["site"]
    return {
        "number": meta["number"],
        "slug": f"{meta['number']}-{slugify(s['title'])}",
        "video_id": video_id,
        "uploaded_at": uploaded_at,
        **s,
    }


def load():
    return json.loads(DATA.read_text()) if DATA.exists() else []


def save(entries):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(sorted(entries, key=lambda x: x["number"]), ensure_ascii=False, indent=1) + "\n")


def add(entry):
    entries = [x for x in load() if x["number"] != entry["number"]]
    entries.append(entry)
    save(entries)


# ---------------------------------------------------------------- 部品


def page(title, description, body, depth, canonical, extra_head=""):
    up = "../" * depth
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<link rel="icon" href="{up}icon.png">
<link rel="stylesheet" href="{up}style.css">
{extra_head}</head>
<body>
<header><div class="bar">
  <img src="{up}icon.png" alt="">
  <a class="name" href="{up}">Painted When?</a>
  <nav><a href="{up}quiz/">All quizzes</a><a href="{up}privacy.html">Privacy</a><a href="{up}terms.html">Terms</a></nav>
</div></header>
<main>
{body}
</main>
<footer><div class="bar">© 2026 Painted When? · <a href="{up}privacy.html">Privacy Policy</a> · <a href="{up}terms.html">Terms of Service</a></div></footer>
</body>
</html>
"""


def card(x, prefix):
    return f"""<a class="card" href="{prefix}{e(x['slug'])}/">
  <img src="{e(x['image'])}" alt="" loading="lazy">
  <span class="card-no">Quiz #{x['number']}</span>
  <span class="card-title">{e(x['title'])}</span>
  <span class="card-artist">{e(x['artist'])}</span>
</a>"""


def quiz_page(x, prev, nxt):
    by = x["artist"] if not x.get("artist_unknown") else "an unknown artist"
    title = f"When was “{x['title']}” by {by} painted? — Painted When? Quiz #{x['number']}"
    desc = (f"Art quiz #{x['number']}: guess the year {by} painted “{x['title']}”. "
            f"Choices: {' / '.join(x['choices'])}. Answer, artwork details and the museum link inside.")
    choices = "\n".join(
        f'    <button type="button" class="choice" data-i="{i}">{e(c)}</button>' for i, c in enumerate(x["choices"]))
    details = " · ".join(p for p in (x.get("date"), x.get("medium")) if p)
    nav = []
    if prev:
        nav.append(f'<a href="../{e(prev["slug"])}/">← Quiz #{prev["number"]}</a>')
    nav.append('<a href="../">All quizzes</a>')
    if nxt:
        nav.append(f'<a href="../{e(nxt["slug"])}/">Quiz #{nxt["number"]} →</a>')
    ld = {
        "@context": "https://schema.org", "@type": "VisualArtwork",
        "name": x["title"], "image": x["image"], "url": x["museum_url"],
        "creator": {"@type": "Person", "name": x["artist"]},
        "dateCreated": x.get("date"), "artMedium": x.get("medium"),
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
    }
    extra = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>\n'
    body = f"""  <p class="muted">Quiz #{x['number']} · {e(x['museum'])}</p>
  <h1>When was this painted?</h1>
  <div class="quiz-layout">
    <div class="short">
      <iframe src="https://www.youtube-nocookie.com/embed/{e(x['video_id'])}" title="Painted When? Quiz #{x['number']}"
        loading="lazy" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
        allowfullscreen></iframe>
    </div>
    <div class="quiz">
      <p>Pick a year, then check the answer.</p>
      <div class="choices" data-answer="{x['answer']}">
{choices}
      </div>
      <button type="button" class="reveal">Show the answer</button>
      <div class="answer" hidden>
        <p class="answer-year">Answer: <strong>{e(x['choices'][x['answer']])}</strong></p>
        <img class="artwork" src="{e(x['image'])}" alt="{e(x['title'])} by {e(by)}" loading="lazy">
        <h2>{e(x['title'])}</h2>
        <p><strong>{e(x['artist'])}</strong>{(' — ' + e(x['artist_bio'])) if x.get('artist_bio') else ''}</p>
        <p class="muted">{e(details)}</p>
        <p><a href="{e(x['museum_url'])}">See it at {e(x['museum'])}</a></p>
        <p class="muted">Image: {e(x['museum'])}, Public Domain (CC0). This site is not affiliated with the museum.</p>
      </div>
    </div>
  </div>
  <p class="pager">{' · '.join(nav)}</p>
  <p><a href="{CHANNEL}">More quizzes every day on YouTube: @painted-when</a></p>
  <script>
  (function () {{
    var box = document.querySelector(".choices"), ans = +box.dataset.answer;
    var panel = document.querySelector(".answer"), btn = document.querySelector(".reveal");
    function reveal(picked) {{
      box.querySelectorAll(".choice").forEach(function (b) {{
        var i = +b.dataset.i;
        b.disabled = true;
        if (i === ans) b.classList.add("right");
        else if (i === picked) b.classList.add("wrong");
      }});
      panel.hidden = false; btn.hidden = true;
    }}
    box.addEventListener("click", function (ev) {{
      var b = ev.target.closest(".choice"); if (b) reveal(+b.dataset.i);
    }});
    btn.addEventListener("click", function () {{ reveal(-1); }});
  }})();
  </script>"""
    return page(title, desc, body, 2, f"{SITE}/quiz/{x['slug']}/", extra)


def list_page(entries):
    cards = "\n".join(card(x, "") for x in reversed(entries))
    body = f"""  <h1>All quizzes</h1>
  <p>Every Painted When? quiz so far, newest first. Open one to try it and see the answer.</p>
  <div class="cards">
{cards}
  </div>"""
    return page("All quizzes — Painted When?",
                "Every Painted When? art quiz: famous public-domain paintings from The Met and the Art Institute "
                "of Chicago. Guess the year each one was painted.", body, 1, f"{SITE}/quiz/")


def latest_block(entries):
    cards = "\n".join(card(x, "quiz/") for x in list(reversed(entries))[:LATEST])
    return f"""<!-- LATEST:START (site_gen.py が書き換える) -->
  <h2>Latest quizzes</h2>
  <div class="cards">
{cards}
  </div>
  <p><a href="quiz/">See all quizzes →</a></p>
  <!-- LATEST:END -->"""


def sitemap(entries):
    urls = [f"{SITE}/", f"{SITE}/quiz/"] + [f"{SITE}/quiz/{x['slug']}/" for x in entries]
    items = "\n".join(f"  <url><loc>{e(u)}</loc></url>" for u in urls)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{items}
</urlset>
"""


def build(docs=DOCS):
    entries = sorted(load(), key=lambda x: x["number"])
    qdir = docs / "quiz"
    for i, x in enumerate(entries):
        d = qdir / x["slug"]
        d.mkdir(parents=True, exist_ok=True)
        prev = entries[i - 1] if i > 0 else None
        nxt = entries[i + 1] if i + 1 < len(entries) else None
        (d / "index.html").write_text(quiz_page(x, prev, nxt))
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "index.html").write_text(list_page(entries))
    top = docs / "index.html"
    s = top.read_text()
    s2 = re.sub(r"<!-- LATEST:START.*?<!-- LATEST:END -->", lambda m: latest_block(entries), s, flags=re.S)
    if s2 == s and "LATEST:START" not in s:
        raise SystemExit("docs/index.html に <!-- LATEST:START --> 〜 <!-- LATEST:END --> がありません")
    top.write_text(s2)
    (docs / "sitemap.xml").write_text(sitemap(entries))
    print(f"site: {len(entries)} quizzes")


if __name__ == "__main__":
    build()

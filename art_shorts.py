#!/usr/bin/env python3
"""今日の名画: 美術館のオープンデータから、名画1点を紹介する短い動画を作る。

出典:
  - The Metropolitan Museum of Art Collection API  https://metmuseum.github.io
  - Art Institute of Chicago API                   https://api.artic.edu/docs
どちらもキー不要。画像はパブリックドメイン(isPublicDomain / is_public_domain が true)の作品だけ使う。

使い方:
  python art_shorts.py --demo                      # 仮画像でレイアウト確認(通信なし)
  python art_shorts.py                             # Met から今日の1点(縦型 Shorts、「いつ描かれた？」の3択クイズ)
  python art_shorts.py --style classic             # 縦型で、クイズなしの作品紹介
  python art_shorts.py --tts dummy                 # クイズの読み上げを仮の音で(GOOGLE_TTS_API_KEY があれば Google の声)
  python art_shorts.py --source aic --format wide  # シカゴ美術館から、横型
  python art_shorts.py --audio narration.mp3       # 動画の長さ = 音声 + 1秒
  python art_shorts.py --id 436535                 # 作品を指定(試作用。used.json に記録しない)
  python art_shorts.py --still                     # 動画を作らず、サムネだけ(見栄え確認用)

出力(--out、既定は out/):
  {日付}_{source}_{id}.mp4 / .jpg(作品画像) / .json(作品情報) / .txt(台本) / _thumb.png
  used.json … 使用済みの作品。同じ作品を二度選ばない
"""
import argparse
import hashlib
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import locales

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"
SERIF = FONT_DIR / "LiberationSerif-Regular.ttf"
SERIF_IT = FONT_DIR / "LiberationSerif-Italic.ttf"
SANS = FONT_DIR / "LiberationSans-Regular.ttf"
SANS_BOLD = FONT_DIR / "LiberationSans-Bold.ttf"

TZ = ZoneInfo("Asia/Tokyo")
FPS = 30
DEFAULT_SECONDS = 15.0
ZOOM = 0.07          # 動画の最初から最後までに、作品をこの割合だけ拡大する
USER_AGENT = os.environ.get("ART_SHORTS_USER_AGENT", "art-shorts/0.1 (daily public-domain painting video)")

FORMATS = {"shorts": (1080, 1920), "wide": (1920, 1080)}

# ---------------------------------------------------------------- HTTP


class RateLimiter:
    """前回のリクエストから min_interval 秒たつまで待つ。"""

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self.last = 0.0

    def wait(self):
        dt = time.monotonic() - self.last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self.last = time.monotonic()


# Met は 80リクエスト/秒まで。余裕をもって 1秒に5回まで
MET_LIMIT = RateLimiter(0.2)
# AIC は匿名で 60リクエスト/分。1秒に1回以下(少し余裕をもつ)
AIC_LIMIT = RateLimiter(1.1)


class HTTPStatusError(Exception):
    def __init__(self, status, url):
        super().__init__(f"HTTP {status}: {url}")
        self.status = status


def http_get(url, limiter, headers=None, tries=4):
    """GET してバイト列を返す。429・5xx・通信エラーは間隔をあけて再試行する。"""
    h = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    h.update(headers or {})
    # Met の画像の URL には空白が含まれることがある(例: ".../C5802 89.4.538.jpg")ので、URL として正しい形に直す
    url = urllib.parse.quote(url, safe=":/?&=%#+,;@~!$'()*")
    for attempt in range(tries):
        limiter.wait()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            # Met の配信網はときどき一時的に 403 を返す(2026-11 に確認)ので、Met だけ 403 も再試行する
            retryable = e.code == 429 or e.code >= 500 or (e.code == 403 and "metmuseum" in url)
            if not retryable or attempt == tries - 1:
                raise HTTPStatusError(e.code, url) from e
            wait = float(e.headers.get("Retry-After") or 0) or 2 ** (attempt + 1)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                raise
            wait = 2 ** (attempt + 1)
            print(f"  通信エラー({e})。{wait:.0f}秒後に再試行", file=sys.stderr)
        time.sleep(min(wait, 60))
    raise RuntimeError("unreachable")


def http_json(url, limiter, headers=None):
    return json.loads(http_get(url, limiter, headers).decode("utf-8"))


# ---------------------------------------------------------------- 作品の選択


def clean(s):
    return " ".join(str(s or "").split())


class Met:
    name = "met"
    museum = "The Metropolitan Museum of Art"
    BASE = "https://collectionapi.metmuseum.org/public/collection"
    QUERY = "painting"

    def candidates(self):
        """ハイライト作品のうち画像のあるものの objectID 一覧。"""
        params = urllib.parse.urlencode(
            {"q": self.QUERY, "isHighlight": "true", "hasImages": "true", "limit": 500})
        # 旧 v1/search は廃止済み(2026-11 に 410 Gone を確認)
        data = http_json(f"{self.BASE}/v1.1/search?{params}", MET_LIMIT)
        ids = extract_ids(data)
        if not ids:
            raise RuntimeError(f"Met の検索結果から objectID を読み取れません: {str(data)[:300]}")
        return ids

    def search_artist(self, name):
        """作者名で検索した、画像のある作品の objectID 一覧。"""
        params = urllib.parse.urlencode(
            {"q": name, "artistOrCulture": "true", "hasImages": "true", "limit": 500})
        return extract_ids(http_json(f"{self.BASE}/v1.1/search?{params}", MET_LIMIT))

    def fetch(self, object_id):
        """1作品の情報。使える作品(PD・画像あり・絵画)なら dict、そうでなければ None。"""
        try:
            o = http_json(f"{self.BASE}/v1/objects/{object_id}", MET_LIMIT)
        except HTTPStatusError as e:
            if e.status == 404:
                return None
            raise
        if o.get("isPublicDomain") is not True or not o.get("primaryImage"):
            return None
        if not is_painting(o.get("classification"), o.get("objectName")):
            return None
        return {
            "source": self.name,
            "id": str(o.get("objectID", object_id)),
            "title": clean(o.get("title")) or "Untitled",
            "artist": clean(o.get("artistDisplayName")) or "Unknown artist",
            "artist_prefix": clean(o.get("artistPrefix")),
            "artist_bio": clean(o.get("artistDisplayBio")),
            "date": clean(o.get("objectDate")),
            "year_start": to_int(o.get("objectBeginDate")),
            "year_end": to_int(o.get("objectEndDate")),
            "medium": clean(o.get("medium")),
            "classification": clean(o.get("classification")) or clean(o.get("objectName")),
            "url": o.get("objectURL") or f"https://www.metmuseum.org/art/collection/search/{object_id}",
            "image_url": o["primaryImage"],
            "image_url_small": o.get("primaryImageSmall") or o["primaryImage"],
            "museum": self.museum,
            "credit": "Image: The Metropolitan Museum of Art, Public Domain (CC0)",
            "license": "CC0",
            "tags": [clean(t.get("term")) for t in (o.get("tags") or []) if isinstance(t, dict)],
        }


def extract_ids(data):
    """検索結果から作品IDを取り出す。v1 は {"total", "objectIDs": [...]}。
    v1.1 の形は実レスポンスで未確認なので、ありそうな形をいくつか受け付ける。"""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = None
        for k in ("objectIDs", "objectIds", "results", "data", "items", "objects"):
            if isinstance(data.get(k), list):
                items = data[k]
                break
        if items is None:
            return []
    else:
        return []
    ids = []
    for it in items:
        if isinstance(it, (int, str)):
            ids.append(str(it))
        elif isinstance(it, dict):
            v = it.get("objectID", it.get("objectId", it.get("id")))
            if v is not None:
                ids.append(str(v))
    return list(dict.fromkeys(ids))


def is_painting(classification, object_name):
    s = f"{classification or ''} {object_name or ''}".lower()
    return "painting" in s


class AIC:
    name = "aic"
    museum = "Art Institute of Chicago"
    BASE = "https://api.artic.edu/api/v1"
    QUERY = "painting"
    FIELDS = ("id,title,artist_display,artist_title,date_display,medium_display,"
              "is_public_domain,image_id,artwork_type_title,classification_title,date_start,date_end,"
              "term_titles,subject_titles")
    MAX_PAGES = 10   # 検索APIは先頭1000件(100件×10ページ)までしか返さない
    headers = {"AIC-User-Agent": USER_AGENT}

    def __init__(self):
        self.iiif_url = None
        self._pages = {}

    def _search(self, page):
        if page not in self._pages:
            params = urllib.parse.urlencode(
                {"q": self.QUERY, "fields": self.FIELDS, "limit": 100, "page": page})
            data = http_json(f"{self.BASE}/artworks/search?{params}", AIC_LIMIT, self.headers)
            iiif = (data.get("config") or {}).get("iiif_url")
            if iiif:
                self.iiif_url = iiif.rstrip("/")
            self._pages[page] = data
        return self._pages[page]

    def search_artist(self, name, page=1):
        """作者名で検索した作品の記録(fields 付き)。"""
        params = urllib.parse.urlencode({"q": name, "fields": self.FIELDS, "limit": 100, "page": page})
        data = http_json(f"{self.BASE}/artworks/search?{params}", AIC_LIMIT, self.headers)
        iiif = (data.get("config") or {}).get("iiif_url")
        if iiif:
            self.iiif_url = iiif.rstrip("/")
        return data.get("data") or [], int((data.get("pagination") or {}).get("total_pages") or 1)

    def pick_pages(self, rng):
        """調べるページの順番。1ページ目でページ数を知ってから、ランダムな順に並べる。"""
        first = self._search(1)
        total = int((first.get("pagination") or {}).get("total_pages") or 1)
        pages = list(range(1, min(total, self.MAX_PAGES) + 1))
        rng.shuffle(pages)
        return pages

    def from_record(self, a):
        if a.get("is_public_domain") is not True or not a.get("image_id"):
            return None
        kind = a.get("artwork_type_title") or a.get("classification_title")
        if kind is not None and not is_painting(kind, None):
            return None
        if not self.iiif_url:
            raise RuntimeError("AIC のレスポンスに config.iiif_url がありません")
        name, bio = split_artist_display(a.get("artist_display"))
        return {
            "source": self.name,
            "id": str(a["id"]),
            "title": clean(a.get("title")) or "Untitled",
            "artist": clean(a.get("artist_title")) or name or "Unknown artist",
            "artist_bio": bio,
            "date": clean(a.get("date_display")),
            "year_start": to_int(a.get("date_start")),
            "year_end": to_int(a.get("date_end")),
            "medium": clean(a.get("medium_display")),
            "classification": clean(kind),
            "url": f"https://www.artic.edu/artworks/{a['id']}",
            # 843px 幅が推奨サイズ。クイズの冒頭で一部を大きく映すため、まず 1686px 幅を試し、
            # 取れなければ 843px に戻す(download_image)。1686px は 2026-11 に取得できることを確認
            "image_url": f"{self.iiif_url}/{a['image_id']}/full/1686,/0/default.jpg",
            "image_url_fallback": f"{self.iiif_url}/{a['image_id']}/full/843,/0/default.jpg",
            "image_url_small": f"{self.iiif_url}/{a['image_id']}/full/843,/0/default.jpg",
            "museum": self.museum,
            "credit": "Image: Art Institute of Chicago, CC0",
            "license": "CC0",
            "tags": [clean(t) for t in (a.get("term_titles") or []) + (a.get("subject_titles") or []) if t],
        }

    def fetch(self, artwork_id):
        data = http_json(f"{self.BASE}/artworks/{artwork_id}?fields={self.FIELDS}", AIC_LIMIT, self.headers)
        iiif = (data.get("config") or {}).get("iiif_url")
        if iiif:
            self.iiif_url = iiif.rstrip("/")
        return self.from_record(data.get("data") or {})


def split_artist_display(s):
    """AIC の artist_display を (名前, 国籍・生没年) に分ける。
    実レスポンス(2026-11)では "Georges Seurat (French, 1859–1891)" の1行形式。
    古い記録には "Name\\nFrench, 1859–1891" の改行形式もあるので両方受け付ける。"""
    s = str(s or "").strip()
    if "\n" in s:
        name, _, bio = s.partition("\n")
        return clean(name), clean(bio)
    if s.endswith(")") and " (" in s:
        name, _, bio = s.rpartition(" (")
        return clean(name), clean(bio[:-1])
    return clean(s), ""


SOURCES = {"met": Met, "aic": AIC}
MAX_LOOKUPS = 60   # 作品情報を何件まで取りに行くか(見つからなければ諦める)


def load_used(path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return []


def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# 裸体の作品は出さない(2026-11-28〜)。#52「The Bathers」(ブグロー)が3回しか再生されず、YouTube が
# 裸体の映る動画をおすすめに出しにくくしているとみられるため。美術館の主題のタグ(Met の tags、シカゴ美術館の
# term_titles・subject_titles)に nude などがある作品と、題名に下の語がある作品を除く
NUDE_TAG = re.compile(r"\bnud(e|es|ity)\b|\bnaked\b|\berotic", re.I)
NUDE_TITLE = re.compile(r"\bnud(e|es)\b|\bnaked\b|\bbath(er|ers|ing|sheba)\b|\bvenus\b|\bodalisque\b|\bdana[eë]\b|"
                        r"\bleda\b|\bsusanna\b|\bthree graces\b|\bjudgment of paris\b|\bdiana and\b|\bnymphs?\b|"
                        r"\badam and eve\b|\bmars and venus\b|\bcupid and psyche\b", re.I)


def is_nude(art):
    """裸体が描かれているとみられる作品なら True(タグか題名で判定)。"""
    if any(NUDE_TAG.search(t or "") for t in art.get("tags") or []):
        return True
    return bool(NUDE_TITLE.search(art.get("title") or ""))


def choose_artwork(src, rng, used, today, accept=None):
    """今日の作品を選ぶ。同じ日に同じ source で選んだ作品があれば、それをもう一度使う。
    accept(art) が False を返す作品は選ばない(クイズに使える年がない作品など)。"""
    ok = lambda a: a is not None and not is_nude(a) and (accept is None or accept(a))
    for u in used:
        if u.get("source") == src.name and u.get("date") == today:
            art = src.fetch(u["id"])
            if ok(art):
                print(f"  今日はすでに選んだ作品があります: {u['id']}")
                return art
    used_ids = {u["id"] for u in used if u.get("source") == src.name}
    lookups = 0
    if isinstance(src, Met):
        ids = sorted(src.candidates(), key=lambda x: int(x) if x.isdigit() else 0)
        rng.shuffle(ids)
        print(f"  候補 {len(ids)} 件")
        for oid in ids:
            if oid in used_ids:
                continue
            lookups += 1
            if lookups > MAX_LOOKUPS:
                break
            art = src.fetch(oid)
            if ok(art):
                return art
    else:
        for page in src.pick_pages(rng):
            records = list((src._search(page).get("data") or []))
            rng.shuffle(records)
            for a in records:
                if str(a.get("id")) in used_ids:
                    continue
                art = src.from_record(a)
                if ok(art):
                    return art
            lookups += 1
            if lookups > 5:   # 5ページ見て無ければ諦める(1ページ1リクエスト)
                break
    raise RuntimeError(f"{src.name}: 条件に合う未使用の作品が見つかりません")


SOURCE_ERRORS = 6      # 美術館の API がこの回数失敗したら、その回はもう一方の美術館を使う
FACE_TRIES = 8          # 顔のない作品を探す候補の数。見つからなければ最初の候補を使う
PER_ARTIST = 2          # 1人の画家から出す候補の数(画家がかたよらないように)


def _famous_candidates(src, rng, used, accept, avoid_artists):
    """有名な画家の本人の作品で、未使用・クイズに使えるものを、画家ごとに順に出す。"""
    import artists
    ok = lambda a: a is not None and not is_nude(a) and (accept is None or accept(a))
    used_ids = {u["id"] for u in used if u.get("source") == src.name}
    names = [n for n, _ in artists.FAMOUS]
    rng.shuffle(names)
    names.sort(key=lambda n: n in avoid_artists)   # 直近の画家は後回し(順番は保つ)
    errors = 0
    for name in names[:12]:
        found = 0
        if isinstance(src, Met):
            try:
                ids = [i for i in src.search_artist(name) if i not in used_ids]
            except HTTPStatusError as e:
                errors += 1
                print(f"  {name}: 検索できません({e})。次の画家へ", file=sys.stderr)
                if errors >= SOURCE_ERRORS:
                    raise
                continue
            rng.shuffle(ids)
            for oid in ids[:30]:
                # Met は一時的に 403 を返し続けることがある(2026-11-18 22:17 の失敗)。1点取れなくても次の候補へ進み、
                # 続けて SOURCE_ERRORS 回失敗したら、呼び出し側でもう一方の美術館に切り替える
                try:
                    art = src.fetch(oid)
                except HTTPStatusError as e:
                    errors += 1
                    print(f"  {oid}: 取れません({e})。次の候補へ", file=sys.stderr)
                    if errors >= SOURCE_ERRORS:
                        raise
                    continue
                if ok(art) and artists.find(art["artist"], art.get("artist_prefix", "")) == name:
                    art["famous_artist"] = name
                    yield art
                    found += 1
                    if found >= PER_ARTIST:
                        break
        else:
            records, pages = src.search_artist(name)
            for page in range(2, min(pages, 3) + 1):
                records += src.search_artist(name, page)[0]
            rng.shuffle(records)
            for r in records:
                if str(r.get("id")) in used_ids:
                    continue
                if artists.find(r.get("artist_display") or r.get("artist_title"), "") != name:
                    continue
                # 「and workshop」などは artist_title にだけ書かれていることがある(例: El Greco and workshop)
                if artists.is_attributed_only(r.get("artist_title") or ""):
                    continue
                art = src.from_record(r)
                if ok(art):
                    art["famous_artist"] = name
                    yield art
                    found += 1
                    if found >= PER_ARTIST:
                        break
        if not found:
            print(f"  {name}: {src.name} に未使用の作品なし", file=sys.stderr)


def has_face(art):
    """作品の小さい画像に、はっきりした顔(人物)が描かれているか。調べられなければ None。"""
    import quiz
    try:
        img = download_image(art, small=True)
    except Exception as e:
        print(f"  画像を確かめられません({e})", file=sys.stderr)
        return None
    W, H = img.size
    faces = [f for f in quiz.detect_faces(img) if f[2] * W >= 0.05 * min(W, H)]
    return bool(faces)


def choose_famous(src, rng, used, accept=None, avoid_artists=(), avoid_faces=True, want_face=False):
    """有名な画家(artists.FAMOUS)の本人の作品から、未使用のものを1点選ぶ。
    顔が描かれた作品は見てもらえにくい傾向があった(2026-11-17 の stats.md: 3日目の再生数の平均が
    顔あり 277・顔なし 541)ので、候補を FACE_TRIES 点まで見て、顔のない作品(風景・静物など)を優先する。
    見つからなければ最初の候補を使う(人物画も出る)。"""
    first = None
    for i, art in enumerate(_famous_candidates(src, rng, used, accept, avoid_artists)):
        if not avoid_faces:
            return art
        face = has_face(art)
        art["has_face"] = face
        print(f"  候補: {art['famous_artist']} 「{art['title'][:40]}」 顔{'あり' if face else ('なし' if face is False else '不明')}")
        if (face is True) if want_face else (face is False):
            return art
        first = first or art
        if i + 1 >= FACE_TRIES:
            break
    if first:
        print(f"  {'顔のある' if want_face else '顔のない'}作品が見つからなかったので、最初の候補を使います")
        return first
    raise RuntimeError(f"{src.name}: 有名な画家の未使用の作品が見つかりません")


def download_image(art, small=False):
    """作品の画像。small=True は顔の有無を調べるための小さい画像(Met は primaryImageSmall、AIC は 843px 幅)。"""
    limiter = MET_LIMIT if art["source"] == "met" else AIC_LIMIT
    headers = AIC.headers if art["source"] == "aic" else None
    url = art.get("image_url_small") if small else None
    try:
        raw = http_get(url or art["image_url"], limiter, headers)
    except HTTPStatusError:
        if not art.get("image_url_fallback"):
            raise
        raw = http_get(art["image_url_fallback"], limiter, headers)
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert("RGB")
    # 巨大な原画像(Met は数千px)は扱いやすい大きさに縮める。クイズの冒頭の拡大に使うので大きめに残す
    img.thumbnail((1024, 1024) if small else (4000, 4000), Image.LANCZOS)
    return img


# ---------------------------------------------------------------- デモ用


DEMO = [
    {"title": "The Harvesters", "artist": "Pieter Bruegel the Elder", "date": "1565",
     "medium": "Oil on wood", "year_start": 1565, "year_end": 1565, "aspect": 1.37},
    {"title": "Portrait of a Young Woman with a Water Pitcher, Seated by an Open Window in Morning Light",
     "artist": "Johannes Vermeer", "artist_bio": "Dutch, Delft 1632–1675 Delft",
     "date": "ca. 1662", "medium": "Oil on canvas, with later additions in tempera and gold leaf on the frame",
     "year_start": 1662, "year_end": 1662, "aspect": 0.42},
    {"title": "Wheat Field with Cypresses", "artist": "Vincent van Gogh", "date": "1889",
     "medium": "Oil on canvas", "year_start": 1889, "year_end": 1889, "aspect": 0.8},
    {"title": "Panorama of the Bay", "artist": "Unknown artist", "date": "ca. 1820",
     "medium": "Watercolor", "year_start": 1818, "year_end": 1822, "aspect": 3.2},
]


def demo_artwork(rng, index=None):
    index = rng.randrange(len(DEMO)) if index is None else index % len(DEMO)
    d = dict(DEMO[index])
    aspect = d.pop("aspect")
    w = 1600 if aspect >= 1 else int(1600 * aspect)
    h = int(w / aspect)
    # 色のグラデーションと円で、作品らしき仮画像を作る
    y, x = np.mgrid[0:h, 0:w]
    c1, c2 = np.array(rng.choice([(40, 60, 90), (90, 60, 30), (30, 70, 50)])), np.array((220, 190, 120))
    t = (y / h)[..., None]
    arr = (c1 * (1 - t) + c2 * t)
    for _ in range(14):
        cx, cy, r = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(0.05, 0.25) * min(w, h)
        col = np.array([rng.randint(30, 255) for _ in range(3)])
        m = (((x - cx) ** 2 + (y - cy) ** 2) < r * r)[..., None]
        arr = np.where(m, arr * 0.4 + col * 0.6, arr)
    img = Image.fromarray(arr.astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))
    ImageDraw.Draw(img).rectangle([0, 0, w - 1, h - 1], outline=(0, 0, 0), width=6)
    art = {"source": "demo", "id": f"demo{index}",
           "artist_bio": "", "classification": "Paintings", "url": "https://example.org/",
           "image_url": "", "museum": "Demo Museum", "credit": "Image: Demo Museum, Public Domain (CC0)",
           "license": "CC0", **d}
    return art, img


# ---------------------------------------------------------------- レイアウト


def font(path, size):
    return ImageFont.truetype(str(path), size)


def wrap(text, fnt, max_w, max_lines):
    """単語単位で折り返す。max_lines を超えたら最後の行を … で切る。"""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if fnt.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    # 1単語が幅を超える場合は文字単位で詰める
    out = []
    for ln in lines:
        while fnt.getlength(ln) > max_w and len(ln) > 1:
            ln = ln[:-1]
        out.append(ln)
    if len(out) > max_lines:
        out = out[:max_lines]
        last = out[-1]
        while last and fnt.getlength(last + "…") > max_w:
            last = last[:-1].rstrip()
        out[-1] = last.rstrip(",;:") + "…"
    return out


def fit_title(text, path, max_w, sizes, max_lines):
    """題名は大きい字から試し、max_lines 行に収まる最大の大きさを使う(収まらなければ最小で … 切り)。"""
    for s in sizes:
        f = font(path, s)
        lines = wrap(text, f, max_w, 99)
        if len(lines) <= max_lines:
            return f, lines
    f = font(path, sizes[-1])
    return f, wrap(text, f, max_w, max_lines)


class TextBlock:
    """縦に並ぶ文字の行(要素ごとにフェードインさせるため、要素単位の透明レイヤーにする)。"""

    def __init__(self, width, align):
        self.width = width
        self.align = align
        self.items = []   # (group, font, line, color, line_height)

    def add(self, group, fnt, lines, color, spacing=1.18, gap_before=0):
        if gap_before:
            self.items.append((group, None, "", None, gap_before))
        for ln in lines:
            self.items.append((group, fnt, ln, color, int(fnt.size * spacing)))

    @property
    def height(self):
        return sum(it[4] for it in self.items)

    def render(self):
        """group ごとの RGBA レイヤー(サイズ width×height)を返す。"""
        h = max(1, self.height)
        layers = {}
        y = 0
        for group, fnt, line, color, lh in self.items:
            layer = layers.setdefault(group, Image.new("RGBA", (self.width, h), (0, 0, 0, 0)))
            if fnt is not None:
                d = ImageDraw.Draw(layer)
                x = {"left": 0, "center": self.width / 2}[self.align]
                anchor = {"left": "ls", "center": "ms"}[self.align]
                baseline = y + int(lh * 0.8)
                # 読みやすいよう、ぼかした影をつける
                shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
                ImageDraw.Draw(shadow).text((x, baseline + 2), line, font=fnt, fill=(0, 0, 0, 200), anchor=anchor)
                shadow = shadow.filter(ImageFilter.GaussianBlur(4))
                layer.alpha_composite(shadow)
                d.text((x, baseline), line, font=fnt, fill=color, anchor=anchor)
            y += lh
        return layers


def build_text(art, width, align, scale=1.0):
    s = lambda v: max(10, int(v * scale))
    tb = TextBlock(width, align)
    f_title, title_lines = fit_title(art["title"], SERIF_IT, width, [s(66), s(58), s(50), s(44)], 3)
    tb.add("title", f_title, title_lines, (250, 246, 236, 255), spacing=1.15)
    tb.add("artist", font(SERIF, s(42)), wrap(art["artist"], font(SERIF, s(42)), width, 2),
           (236, 214, 160, 255), gap_before=s(18))
    meta = " · ".join(x for x in (art.get("date"), art.get("medium")) if x)
    if meta:
        f = font(SERIF, s(34))
        tb.add("meta", f, wrap(meta, f, width, 2), (215, 210, 200, 255), gap_before=s(8))
    return tb


def cover(img, size):
    return ImageOps.fit(img, size, Image.LANCZOS)


def make_background(img, size):
    """作品を画面いっぱいに広げてぼかし、暗くした背景。"""
    small = cover(img, (size[0] // 8, size[1] // 8)).filter(ImageFilter.GaussianBlur(6))
    bg = small.resize(size, Image.BICUBIC).filter(ImageFilter.GaussianBlur(10))
    arr = np.asarray(bg).astype(np.float32) * 0.42
    # 周辺を少し暗くする
    h, w = arr.shape[:2]
    y, x = np.ogrid[0:h, 0:w]
    r = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2)
    arr *= (1 - 0.35 * np.clip(r - 0.4, 0, 1))[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def frame_dims(img, box_w, box_h, border):
    """作品+額縁が box に収まる大きさ。返り値は作品部分(内側)の幅・高さ。"""
    iw, ih = img.size
    k = min((box_w - 2 * border) / iw, (box_h - 2 * border) / ih)
    return max(1, int(iw * k)), max(1, int(ih * k))


def make_frame(inner_w, inner_h, border):
    """額縁(中央が透明)。外側の暗い木枠と、内側の細い金の縁。"""
    W, H = inner_w + 2 * border, inner_h + 2 * border
    fr = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(fr)
    steps = border
    for i in range(steps):
        t = i / max(1, steps - 1)
        # 外から内へ:暗い茶 → 少し明るい → 金の縁
        base = np.array([58, 40, 26]) * (1 - t) + np.array([96, 70, 42]) * t
        if i >= steps - max(3, border // 6):
            base = np.array([196, 160, 92])
        d.rectangle([i, i, W - 1 - i, H - 1 - i], outline=tuple(int(c) for c in base) + (255,))
    d.rectangle([border, border, W - 1 - border, H - 1 - border], fill=(0, 0, 0, 0))
    return fr


def drop_shadow(size, offset, radius, pad):
    W, H = size[0] + 2 * pad, size[1] + 2 * pad
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([pad + offset, pad + offset, pad + offset + size[0], pad + offset + size[1]],
                                 fill=(0, 0, 0, 170))
    return sh.filter(ImageFilter.GaussianBlur(radius))


class Layout:
    """静的な部品(背景・額縁・文字レイヤー)と、それぞれの位置。"""

    def __init__(self, art, img, fmt):
        self.size = W, H = FORMATS[fmt]
        self.fmt = fmt
        self.bg = make_background(img, self.size).convert("RGBA")
        credit = f"{art['museum']} · Public Domain (CC0)"
        if fmt == "shorts":
            # Shorts は画面下部(約420px)にタイトル・チャンネル名、右端(約150px)にボタンが重なる。
            # 文字はその手前に収め、右側も空ける
            margin_x, top, safe_bottom = 80, 150, H - 430
            text_w = W - margin_x - 170
            self.text = build_text(art, text_w, "left")
            f_credit = font(SANS, 28)
            text_h = self.text.height
            gap = 44
            box_w = W - 2 * margin_x
            box_h = safe_bottom - top - gap - text_h - 50
            self.border = 26
            iw, ih = frame_dims(img, box_w, box_h, self.border)
            fw, fh = iw + 2 * self.border, ih + 2 * self.border
            block_h = fh + gap + text_h + 50
            y0 = top + max(0, (safe_bottom - top - block_h) // 2)
            self.frame_xy = ((W - fw) // 2, y0)
            self.text_xy = (margin_x, y0 + fh + gap)
            self.credit_xy = (margin_x, self.text_xy[1] + text_h + 22)
        else:
            margin, gap = 90, 80
            self.border = 24
            text_w = 620
            box_w = W - 2 * margin - gap - text_w
            box_h = H - 2 * margin - 40
            iw, ih = frame_dims(img, box_w, box_h, self.border)
            fw, fh = iw + 2 * self.border, ih + 2 * self.border
            # 横長の作品は額縁が小さくなるので、空いた幅を文字に回す
            text_w = W - 2 * margin - gap - fw
            text_w = max(560, min(text_w, 860))
            self.text = build_text(art, text_w, "left", scale=0.95)
            total_w = fw + gap + text_w
            x0 = (W - total_w) // 2
            self.frame_xy = (x0, (H - 40 - fh) // 2)
            text_h = self.text.height
            self.text_xy = (x0 + fw + gap, (H - 40 - text_h) // 2)
            f_credit = font(SANS, 24)
            self.credit_xy = (self.text_xy[0], self.text_xy[1] + text_h + 26)
        self.inner = (iw, ih)
        self.frame = make_frame(iw, ih, self.border)
        self.shadow_pad = 40
        self.shadow = drop_shadow(self.frame.size, 10, 18, self.shadow_pad)
        self.text_layers = self.text.render()
        # 出典は最初から最後まで出しておく
        cl = Image.new("RGBA", (W, f_credit.size * 2), (0, 0, 0, 0))
        ImageDraw.Draw(cl).text((0, int(f_credit.size * 1.2)), credit, font=f_credit,
                                fill=(205, 200, 190, 220), anchor="ls")
        self.credit_layer = cl
        # 作品は内側の 1.25 倍ほどに縮めておく(毎フレームの拡大縮小を軽くする)
        src = img.copy()
        src.thumbnail((int(iw * 1.25), int(ih * 1.25)), Image.LANCZOS)
        self.src = src
        base = self.bg.copy()
        base.alpha_composite(self.shadow, (self.frame_xy[0] - self.shadow_pad, self.frame_xy[1] - self.shadow_pad))
        base.alpha_composite(self.credit_layer, self.credit_xy)
        self.base = base


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


# 文字の出るタイミング(秒): (開始, フェードの長さ)
FADES = {"title": (0.8, 1.0), "artist": (1.8, 1.0), "meta": (2.8, 1.0)}


def render_frame(L, t, duration):
    """時刻 t の1フレーム(RGB)。"""
    frame = L.base.copy()
    # ゆっくりズーム:作品の中心に向かって切り抜き範囲を狭める
    z = 1 + ZOOM * ease(t / duration) if duration > 0 else 1
    sw, sh = L.src.size
    cw, ch = sw / z, sh / z
    x0, y0 = (sw - cw) / 2, (sh - ch) / 2
    art = L.src.resize(L.inner, Image.BICUBIC, box=(x0, y0, x0 + cw, y0 + ch))
    fx, fy = L.frame_xy
    frame.paste(art, (fx + L.border, fy + L.border))
    frame.alpha_composite(L.frame, (fx, fy))
    for group, layer in L.text_layers.items():
        start, length = FADES.get(group, (0, 0.01))
        a = ease((t - start) / length)
        if a <= 0:
            continue
        if a < 1:
            layer = layer.copy()
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
        frame.alpha_composite(layer, L.text_xy)
    # 最初と最後は黒からフェード
    fade = min(ease(t / 0.6), ease((duration - t) / 0.6)) if duration > 1.5 else 1
    rgb = frame.convert("RGB")
    if fade < 1:
        rgb = Image.blend(Image.new("RGB", rgb.size, (0, 0, 0)), rgb, fade)
    return rgb


def thumbnail(L):
    """サムネ:全部の文字が出ている状態(ズームは途中)。"""
    t_all = max(start + length for start, length in FADES.values()) + 0.5
    return render_frame(L, t_all, 1e9)


# ---------------------------------------------------------------- 動画


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def render_video(size, frame_at, duration, out_path, audio=None):
    """frame_at(t) が返す RGB 画像を FPS 枚/秒で ffmpeg に渡して mp4 にする。"""
    W, H = size
    n = int(round(duration * FPS))
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if audio:
        # 音声の後ろを無音で埋めて、映像の長さに合わせる
        cmd += ["-i", str(audio), "-af", "apad", "-map", "0:v", "-map", "1:a"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a"]
    cmd += ["-t", f"{n / FPS:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(n):
            p.stdin.write(frame_at(i / FPS).tobytes())
            if i % (FPS * 5) == 0:
                print(f"  {i / FPS:4.0f}s / {duration:.0f}s", flush=True)
    finally:
        p.stdin.close()
        if p.wait() != 0:
            raise RuntimeError("ffmpeg が失敗しました")


# ---------------------------------------------------------------- 台本


def script_text(art):
    """台本の下書き(英語)。のちに Claude API による解説に置き換える予定。"""
    parts = [f"Today's painting is {art['title']}"]
    if art["artist"] and art["artist"].lower() not in ("unknown artist", "unidentified artist", "anonymous"):
        parts[0] += f", by {art['artist']}"
    parts[0] += "."
    if art.get("date"):
        parts.append(f"It dates from {art['date']}.")
    if art.get("medium"):
        parts.append(f"Medium: {art['medium']}.")
    museum = art["museum"] if art["museum"].startswith("The ") else f"the {art['museum']}"
    parts.append(f"It is in the collection of {museum}, and the image is in the public domain.")
    return "\n".join(textwrap.fill(p, 80) for p in parts) + "\n"


# ---------------------------------------------------------------- YouTube のタイトル・説明文


def _yt_text(s):
    """YouTube はタイトル・説明文の < > を受け付けないので置き換える。"""
    return str(s).replace("<", "‹").replace(">", "›")


UNKNOWN_ARTISTS = ("unknown artist", "unidentified artist", "anonymous")


def site_fields(art):
    """サイト(site_gen.py)の作品ページに載せる情報。"""
    qz = art["quiz"]
    import artists
    artist = (art.get("famous_artist") or artists.find(art.get("artist") or "", art.get("artist_prefix", ""))
              or art.get("artist") or "Unknown artist")
    return {
        "title": art["title"],
        "artist": artist,
        "artist_bio": art.get("artist_bio") or "",
        "artist_unknown": artist.lower() in UNKNOWN_ARTISTS,
        "date": art.get("date") or "",
        "medium": art.get("medium") or "",
        "museum": art["museum"],
        "museum_url": art["url"],
        "image": art.get("image_url_small") or art["image_url"],
        "source": art["source"],
        "id": art["id"],
        "choices": qz["choices"],
        "answer": qz["answer"],
    }


# 題名の型(答えの年は書かない)。偶数番の回は元の型(classic)、奇数番の回はほかの型を順に回す
# (2026-11-17〜。元の型の最新の平均 656 に対し、新しい型はどれも 0〜427 だったので、元の型の割合を半分に増やした)。
# 奇数番の回では、埋められない型・過去と同じ題名・前の回と同じ型は飛ばす。
# {artist}: artists.py の有名な画家の名前、{last}: その姓、{work}: 作品名(短いときだけ)
CLASSIC_EVERY = 2       # この本数に1本は元の型(classic)

TITLES = [
    ("", "classic", "When was this painted? 🎨 Daily Art Quiz"),
    ("artist", "artist", "When did {artist} paint this? 🎨 Art Quiz"),
    ("", "guess", "Can you guess when this was painted? 🎨"),
    ("artist", "artist_but_when", "{artist} painted this... but when? 🎨"),
    ("work", "work", "Art quiz: when was \u201c{work}\u201d painted? 🎨"),
    ("", "how_old", "How old is this painting? Guess the year 🎨"),
    ("artist", "artist_year", "Can you guess the year of this {artist} painting? 🎨"),
    ("", "zoom", "Zoom out and guess the year this was painted 🎨"),
    ("last", "masterpiece", "Guess when this {last} masterpiece was painted 🎨"),
    ("", "art_lovers", "Art lovers: can you date this painting? 🎨"),
    ("work artist", "work_artist", "\u201c{work}\u201d by {artist}: guess the year 🎨"),
    ("", "which_year", "Which year was this painted? Take a guess 🎨"),
]


# 浮世絵の回(ukiyoe.py)の題名。版画は「描いた」ではなく「作った」(made)
UKIYOE_TITLES = [
    ("", "ukiyoe_when", "When was this Japanese woodblock print made? 🎨"),
    ("artist", "ukiyoe_artist", "When did {artist} make this woodblock print? 🎨"),
    ("", "ukiyoe_guess", "Ukiyo-e quiz: guess the year this print was made 🗾"),
]


# 「服装から当てる」回の題名(その回の中で順に回す)
FASHION_TITLES = [
    ("fashion_clothes", "Can you date this painting from the clothes alone? 👗"),
    ("fashion_century", "Which century? The clothes are the clue 🎨"),
    ("fashion_detective", "Fashion detectives: guess the century of this painting 👒"),
]


def title_vals(art):
    """題名の型に入れる値。画家は artists.py の有名な画家のときだけ。"""
    famous = art.get("famous_artist")
    work = (art.get("title") or "").strip()
    return {"artist": famous, "last": famous.split()[-1] if famous else None,
            # 作品名に年が入っていると答えが分かるので使わない(例: "View of Toledo, 1600")
            "work": work if work and len(work) <= 40 and "<" not in work and not re.search(r"\d{3,4}", work) else None}


def video_title(art, number, used=(), last_style=None):
    """(題名, 型)。答え(年)は書かない。型は upload_history.json の title_style に残し、stats.md で比べる。
    画家の名前を出す型は、artists.py の有名な画家のときだけ(名前で検索されやすくするため)。"""
    vals = title_vals(art)
    if art.get("fashion"):
        import fashion as F
        style, t = FASHION_TITLES[number // F.FASHION_EVERY % len(FASHION_TITLES)]
        return t, style
    if art.get("ukiyoe"):
        need, style, tpl = UKIYOE_TITLES[number // 6 % len(UKIYOE_TITLES)]
        if need and not vals.get(need):
            need, style, tpl = UKIYOE_TITLES[0]
        return tpl.format(**{k: v for k, v in vals.items() if v}), style
    if number % CLASSIC_EVERY == 0:
        return TITLES[0][2], TITLES[0][1]       # 元の型は毎回同じ題名でよい(番号で区別される)
    used = {re.sub(r"^\[\d+\]\s*", "", t) for t in used}
    others = TITLES[1:]
    for k in range(len(others)):
        need, style, tpl = others[(number // CLASSIC_EVERY + k) % len(others)]
        if any(not vals.get(w) for w in need.split()):
            continue
        t = tpl.format(**{k2: v for k2, v in vals.items() if v})
        if len(f"[{number}] {t}") <= 100 and t not in used and style != last_style:
            return t, style
    return "When was this painted? 🎨 Daily Art Quiz", "classic"


# 姉妹チャンネル(説明欄の終わりで紹介する。上級者向け機能でリンクがクリックできる)
SISTERS = [
    ("🗺️ Wait, That Big? — the true size of countries on the map", "https://www.youtube.com/@wait-that-big"),
    ("🛰️ Guess From Space — name famous places from satellite images", "https://www.youtube.com/@guess-from-space"),
    ("🔍 Too Close to Tell — guess the museum object from an extreme close-up", "https://www.youtube.com/@too-close-to-tell"),
]


def latest_long():
    """いちばん新しい公開の通常動画(Art History Timeline Challenge)の (番号, URL)。なければ None。"""
    try:
        hist = json.loads((HERE / "longform_history.json").read_text() or "[]")
    except (OSError, ValueError):
        return None
    now = datetime.now().astimezone()
    pub = [h for h in hist if h.get("video_id") and h.get("privacy") == "public"      # 予約投稿で、まだ公開前の回は出さない
           and (not h.get("publish_at") or datetime.fromisoformat(h["publish_at"].replace("Z", "+00:00")) <= now)]
    return (pub[-1]["number"], f"https://youtu.be/{pub[-1]['video_id']}") if pub else None


# 予告編の Short は 2026-11-28 にやめた(#46 は3日目で7回、#48 は106回と、ふつうの回の平均 436 を大きく下回り、
# 通常動画もほとんど見られていないため)。説明欄の通常動画へのリンク(latest_long)はそのまま。True に戻せば再開する
TEASER_ENABLED = False
TEASER_DAYS = 3         # 通常動画を投稿してからこの日数のうちに、予告編の Short を1本出す


def teaser_plan(history, now=None):
    """(通常動画の番号, URL, 作品の key, 何問目, 問題の数) か None。
    いちばん新しい通常動画(Art History Timeline Challenge)を投稿してから TEASER_DAYS 日以内で、まだ予告編を
    出していなければ、その動画の作品から1点(最初の2問と、Shorts に出した作品は避ける)を選ぶ。"""
    from datetime import timezone
    now = now or datetime.now(timezone.utc)
    try:
        hist = json.loads((HERE / "longform_history.json").read_text() or "[]")
    except (OSError, ValueError):
        return None
    hist = [h for h in hist if h.get("video_id")]
    if not hist:
        return None
    lg = max(hist, key=lambda x: x["number"])
    if any(h.get("teaser") == lg["number"] for h in history):
        return None
    start = datetime.fromisoformat((lg.get("publish_at") or lg["uploaded_at"]).replace("Z", "+00:00"))     # 予約投稿なら公開の時刻から
    if now < start or (now - start).total_seconds() > TEASER_DAYS * 86400:
        return None
    used = {h.get("key") for h in history}
    keys = lg["keys"]
    for i in sorted(range(len(keys)), key=lambda i: (i < 2, i)):
        if keys[i] not in used:
            return lg["number"], f"https://youtu.be/{lg['video_id']}", keys[i], i + 1, len(keys)
    return None


def teaser_overlay(n_long, round_no, total, hide_at):
    """冒頭の場面へ戻る直前の約2秒、上に「Painting 4 of 10 · Timeline Challenge #1 / Play all 10 paintings!」。"""
    import quiz as _q
    l1 = _q.text_layer([f"Painting {round_no} of {total} · Timeline Challenge #{n_long}"], font(SANS_BOLD, 38),
                       (250, 246, 236, 255), 1080)
    l2 = _q.text_layer([f"Play all {total} paintings!"], font(SANS_BOLD, 64), _q.GOLD + (255,), 1080)
    hgt = l1.height + l2.height + 36
    band = Image.new("RGBA", (1080, hgt), (0, 0, 0, 0))
    ImageDraw.Draw(band).rounded_rectangle([40, 0, 1040, hgt], radius=28, fill=(20, 16, 24, 235),
                                           outline=_q.GOLD + (220,), width=4)
    band.alpha_composite(l1, (0, 12))
    band.alpha_composite(l2, (0, 12 + l1.height))

    def overlay(img, t):
        a = ease((t - (hide_at - 2.4)) / 0.4) * (1 - ease((t - hide_at) / 0.3))
        if a > 0:
            img.alpha_composite(_q.with_alpha(band, a), (0, 110))
        return img
    return overlay


def youtube_meta(art, number, history=()):
    """クイズ動画のタイトル・説明文・タグ。答えは説明文の下の方にだけ書く(タイトルには書かない)。"""
    qz = art["quiz"]
    answer = qz["choices"][qz["answer"]]
    title, style = video_title(art, number, [h.get("title", "") for h in history],
                               history[-1].get("title_style") if history else None)
    artist = art.get("artist") or "Unknown artist"
    work = f"\"{art.get('title_full') or art['title']}\" by {artist}" if artist.lower() not in (
        "unknown artist", "unidentified artist", "anonymous") else f"\"{art['title']}\" (artist unknown)"
    import narration
    leads = ["Can you guess the year? Comment your answer before the reveal! 🎨",
             "Guess the year before the answer appears! 🎨",
             "Pause and pick a year, then watch the reveal! 🖼️",
             "How good is your eye for art history? Guess the year! 🎨"]
    fact = narration.age_fact(art, number)
    clue = (art.get("fashion") or {}).get("clue")
    if clue:
        leads = ["Look at the clothes: which century was this painted in? Comment your guess! 👗"]
    ukiyoe = bool(art.get("ukiyoe"))
    if ukiyoe:
        # 「Edo period」とは書かない(月岡芳年など明治の作品もあるため)
        leads = ["A Japanese woodblock print (ukiyo-e). Guess the year it was made! 🎨"]
    import quiz as _quiz
    import timeline_facts
    then = timeline_facts.fact(art, _quiz.quiz_year(art))
    tz = art.get("teaser")
    lines = [
        *([f"▶️ This is painting {tz['round']} of Art History Timeline Challenge #{tz['long']}. "
           f"Play all {tz['total']} paintings: {tz['url']}", ""] if tz else []),
        leads[number % len(leads)],
        "",
        "Choices: " + " / ".join(qz["choices"]),
        "",
        "⬇️ Answer below ⬇️",
        ".", ".", ".",
        f"Answer: {answer}",
        work,
        *([clue + "."] if clue else []),
        *([fact] if fact else []),
        *([then + "."] if then else []),
        " · ".join(x for x in (art.get("date"), art.get("medium")) if x),
        art["museum"],
        art["url"],
        "",
        f"Image: {art['museum']}, Public Domain (CC0). This channel is not affiliated with the museum.",
        "",
        *([f"▶️ Try the full 10-painting Art History Timeline Challenge #{latest_long()[0]}: {latest_long()[1]}", ""]
          if latest_long() else []),
        "More quizzes from the same creator:",
        *[f"{t}: {u}" for t, u in SISTERS],
        "",
        ("#arthistory #artquiz #ukiyoe #japaneseart #shorts" if ukiyoe else
         "#arthistory #artquiz #painting #shorts" + (" #fashionhistory" if clue else "")),
    ]
    tags = ["art quiz", "art history", "painting", "guess the year", "museum", "fine art", "art", "quiz"]
    if ukiyoe:
        tags = ["art quiz", "art history", "ukiyo-e", "japanese woodblock print", "japanese art",
                "guess the year", "museum", "quiz"]
    if clue:
        tags += ["fashion history", "historical fashion", "costume history"]
    if artist.lower() not in ("unknown artist", "unidentified artist", "anonymous"):
        tags.append(artist)
    return {
        # 番号を先頭に置く(スマホの YouTube Studio の一覧でタイトルが切れても番号が見えるように)。
        # 「#15」だとハッシュタグ扱いされることがあるので「[15]」にする
        "title": _yt_text(f"[{number}] {title}")[:100],
        "title_style": style,
        "description": _yt_text("\n".join(lines))[:4900],
        # 題名と説明の翻訳(日本語・スペイン語・フランス語・ドイツ語・ポルトガル語)
        "localizations": locales.build(style, number, title_vals(art), _yt_text("\n".join(lines))[:4800],
                                       fashion=bool(clue), ukiyoe=ukiyoe),
        "tags": tags,
        "answer": answer,
    }


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=sorted(SOURCES) + ["auto"], default="met",
                    help="auto: 投稿記録(--history)の最後の回と違う美術館(Met とシカゴ美術館を交互に)")
    ap.add_argument("--history", help="投稿記録 upload_history.json。ここにある作品は選ばない。"
                                      "指定すると、投稿用の out/meta.json(タイトル・説明文など)も書き出す")
    ap.add_argument("--format", choices=sorted(FORMATS), default="shorts")
    ap.add_argument("--style", choices=["quiz", "classic"],
                    help="quiz: 「いつ描かれた？」の3択(縦型のみ。縦型の既定)/ classic: 作品紹介(横型の既定)")
    ap.add_argument("--audio", help="classic のナレーション音声。動画の長さは音声+1秒になる")
    ap.add_argument("--tts", choices=["google", "dummy", "none"],
                    help="quiz の読み上げ。google は API キー(環境変数 GOOGLE_TTS_API_KEY か Network secrets)が必要。"
                         "dummy は仮の音(タイミング確認用)。既定: キーがあれば google、なければ none")
    ap.add_argument("--seconds", type=float, help="音声なしのときの長さ(既定: quiz 13秒 / classic 15秒)")
    ap.add_argument("--hook", action="store_true",
                    help="quiz のフック版: 選択肢と残り時間のバーを最初から出し、0秒に効果音、第一声は「Quick, guess the year!」")
    ap.add_argument("--variant", choices=["base", "hook", "auto"],
                    help="冒頭の版。auto は投稿記録(--history)の直前の1本と逆の版(比較のため1本ごとに交互にする)")
    ap.add_argument("--any-artist", action="store_true",
                    help="有名な画家(artists.py)に絞らず、以前の選び方(Met はハイライト、AIC は検索結果)で選ぶ")
    ap.add_argument("--seed", help="作品選びのシード(既定は日付+source)")
    ap.add_argument("--id", help="作品IDを指定(試作用。used.json に記録しない)")
    ap.add_argument("--fashion", nargs="?", const="auto",
                    help="「服装から当てる」回(fashion.py)。ID を付けるとその作品(試作用)。"
                         "付けなくても、--history があれば番号が fashion.FASHION_EVERY の倍数の回は自動でこの回になる")
    ap.add_argument("--ukiyoe", action="store_true",
                    help="浮世絵の回(ukiyoe.py。試作用)。付けなくても、--history があれば ukiyoe.is_due の回は自動でこの回になる")
    ap.add_argument("--opening", choices=["auto", "header", "plain"], default="auto",
                    help="冒頭の見せ方。header: 上の帯に問いと3つの年を最初から出す / plain: 今まで通り。"
                         "auto: --history があれば番号を4で割った余りが1・2の回は header")
    ap.add_argument("--date", help="日付 YYYY-MM-DD(既定は日本時間の今日)")
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--demo", action="store_true", help="仮画像で作る(通信なし)")
    ap.add_argument("--demo-index", type=int, help="デモの作品番号(0〜3)")
    ap.add_argument("--still", action="store_true", help="動画は作らず、サムネだけ")
    args = ap.parse_args()
    style = args.style or ("quiz" if args.format == "shorts" else "classic")
    if style == "quiz" and args.format != "shorts":
        ap.error("--style quiz は --format shorts だけで使えます")
    if style == "quiz":
        import quiz
        if args.audio:
            ap.error("quiz では --audio ではなく --tts を使います")
    accept = quiz.accept if style == "quiz" else None
    tts = args.tts or ("google" if os.environ.get("GOOGLE_TTS_API_KEY") else "none")

    if not args.still and not shutil.which("ffmpeg"):
        sys.exit("ffmpeg が見つかりません")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    today = args.date or datetime.now(TZ).strftime("%Y-%m-%d")
    history = json.loads(Path(args.history).read_text()) if args.history and Path(args.history).exists() else []
    if args.variant == "auto":
        # 比較を始めてからの本数で、8本周期の並び(hook, hook, base, base, base, base, hook, hook)から選ぶ。
        # - 美術館は1本ごとに交互なので、2本ずつ並べると版と美術館の組み合わせが4通りとも均等に出る
        #   (1本ごとに交互だと、版と美術館が常に同じ組み合わせになり比べられない)
        # - 1日4本なので、4本周期だと毎日同じ時間帯に同じ版が来る。8本周期にして、日ごとに入れ替える
        pattern = ["hook", "hook", "base", "base", "base", "base", "hook", "hook"]
        args.variant = pattern[sum(1 for h in history if h.get("variant")) % len(pattern)]
    if args.variant:
        args.hook = args.variant == "hook"
        print(f"冒頭の版: {args.variant}")
    if args.source == "auto":
        last = history[-1]["source"] if history else "aic"
        args.source = "aic" if last == "met" else "met"
    seed = args.seed or f"{today}:{args.source}"
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))
    used_path = out / "used.json"
    record = False

    import fashion as F
    fashion_item = None
    # 通常動画の予告編の回(週1本)。服装の回より先にする(服装の回は次の5の倍数の回に出る)
    teaser = (teaser_plan(history) if TEASER_ENABLED and style == "quiz" and args.history and not args.demo and not args.id
              else None)
    if teaser:
        print(f"予告編: Art History Timeline Challenge #{teaser[0]} の {teaser[3]}問目 → {teaser[2]}")
        args.source = teaser[2].split(":")[0]
        args.hook = False
    if style == "quiz" and not args.demo and not args.id and not teaser:
        if args.fashion and args.fashion != "auto":
            fashion_item = next((it for it in F.ITEMS if it["id"] == args.fashion), None)
            if not fashion_item:
                sys.exit(f"fashion.ITEMS に {args.fashion} がありません")
        elif args.fashion or (args.history and F.is_due(len(history) + 1)):
            fashion_item = F.pick(history, rng)
            if not fashion_item:
                print("「服装」の回の作品を出し終えたので、ふつうの回にします", file=sys.stderr)
    import ukiyoe as U
    ukiyoe_due = (style == "quiz" and not args.demo and not args.id and not teaser and not fashion_item
                  and (args.ukiyoe or (args.history and U.is_due(len(history) + 1))))
    if fashion_item:
        args.source = fashion_item["source"]
        args.hook = False
    if ukiyoe_due:
        args.source = "aic"
        args.hook = False

    if args.demo:
        art, img = demo_artwork(rng, args.demo_index)
    else:
        src = SOURCES[args.source]()
        print(f"[{args.source}] 作品を選んでいます(seed={seed})")
        if teaser:
            art = src.fetch(teaser[2].split(":", 1)[1])
            if not art or not accept(art):
                sys.exit(f"{teaser[2]} が使えません")
            import artists
            name = artists.find(art["artist"], art.get("artist_prefix", ""))
            if name:
                art["famous_artist"] = name
            art["teaser"] = {"long": teaser[0], "url": teaser[1], "round": teaser[3], "total": teaser[4],
                             "outro": f"That was painting {teaser[3]}. Want {teaser[4] - 1} more? "
                                      "Tap the link to play the full challenge!"}
            used = load_used(used_path)
            record = not args.seed and not args.still and not any(
                u.get("source") == art["source"] and u.get("id") == art["id"] for u in used)
        elif fashion_item:
            art = src.fetch(fashion_item["id"])
            if not art or not accept(art):
                sys.exit(f"{F.key(fashion_item)} が使えません(パブリックドメインでない・制作年の幅が広いなど)")
            import artists
            name = artists.find(art["artist"], art.get("artist_prefix", ""))
            if name:
                art["famous_artist"] = name
            art["fashion"] = {"clue": fashion_item["clue"]}
            used = load_used(used_path)
            record = not args.seed and not args.still and not any(
                u.get("source") == art["source"] and u.get("id") == art["id"] for u in used)
        elif ukiyoe_due:
            used = load_used(used_path) + [{"source": h["source"], "id": h["id"]} for h in history]
            art = None
            try:
                art = U.choose(src, rng, used)
            except Exception as e:          # 美術館の API が失敗したら、ふつうの回にする(投稿は止めない)
                print(f"警告: 浮世絵を選べませんでした({e})", file=sys.stderr)
            if not art:
                print("浮世絵の回の作品が見つからないので、ふつうの回にします", file=sys.stderr)
                ukiyoe_due = False
                recent = [h.get("artist") for h in history[-10:] if h.get("artist")]
                art = choose_famous(src, rng, used, accept, avoid_artists=recent)
            record = not args.seed and not args.still and not any(
                u.get("source") == art["source"] and u.get("id") == art["id"] for u in used)
        elif args.id:
            art = src.fetch(args.id)
            if not art:
                sys.exit(f"{args.id} は使えません(パブリックドメインの絵画で、画像があるものだけ)")
            if accept and not accept(art):
                sys.exit(f"{args.id} は制作年の幅が広い(または不明な)ので、クイズに使えません。--style classic なら使えます")
        else:
            used = load_used(used_path) + [{"source": h["source"], "id": h["id"]}
                                           for h in history]
            # 通常動画(longform.py)で使った作品も選ばない
            lp = HERE / "longform_history.json"
            if lp.exists():
                used += [{"source": k.split(":")[0], "id": k.split(":", 1)[1]}
                         for h in json.loads(lp.read_text() or "[]") for k in h.get("keys", [])]
            if args.any_artist:
                art = choose_artwork(src, rng, used, today, accept)
            else:
                recent = [h.get("artist") for h in history[-10:] if h.get("artist")]
                # 2026-11-26〜 比べる: 偶数番は人物画(顔のある絵)、奇数番は顔のない絵。どちらも冒頭のアップは顔を避ける
                portrait = (len(history) + 1) % 2 == 0
                try:
                    art = choose_famous(src, rng, used, accept, avoid_artists=recent, want_face=portrait)
                except HTTPStatusError as e:
                    other = "aic" if src.name == "met" else "met"
                    print(f"警告: {src.name} の API が失敗し続けたので({e})、この回は {other} から選びます", file=sys.stderr)
                    src = SOURCES[other]()
                    art = choose_famous(src, rng, used, accept, avoid_artists=recent, want_face=portrait)
            record = not args.seed and not args.still and not any(
                u.get("source") == art["source"] and u.get("id") == art["id"] for u in used)
        print(f"  → {art['title']} / {art['artist']} / {art['date']}  {art['url']}")
        img = download_image(art)
    art["date_selected"] = today

    base = f"{today}_{art['source']}_{art['id']}"
    stem = base + {"quiz": "_quiz", "classic": ""}[style] + ("_hook" if args.hook else "") + \
        ("" if args.format == "shorts" else "_wide")
    if style == "quiz":
        # 選択肢は作品ごとに決める(同じ作品なら何度作っても同じ選択肢)
        # 冒頭の帯(quiz.Quiz の header)を4本に2本。人物画の比べ方(偶数・奇数)と重ならないよう、番号を4で割った余りで決める
        header = args.opening == "header" or (args.opening == "auto" and args.history and (len(history) + 1) % 4 in (1, 2))
        q = quiz.Quiz(art, img, random.Random(f"{art['source']}:{art['id']}"), max_year=int(today[:4]),
                      fashion=fashion_item, header=bool(header))
        art["quiz"] = {"question": "Which century? Check the clothes!" if fashion_item else
                       ("When was this print made?" if art.get("ukiyoe") else "When was this painted?"),
                       "choices": q.labels, "answer": q.correct}
        art["number"] = len(history) + 1          # 言い回しを番号で回す(narration.vary)
        if tts != "none":
            import narration
            print(f"読み上げを作っています({tts})")
            q.tl, mix, lines, at = narration.build(art, q, narration.make_tts(tts), hook=args.hook)
            args.audio = out / f"{stem}_voice.wav"
            narration.write_wav(args.audio, mix)
            art["quiz"]["narration"] = {k: {"text": lines[k], "start": round(at[k], 2)} for k in lines}
            art["quiz"]["tts"] = tts
        art["quiz"]["timeline"] = q.tl.as_dict()
        size, thumb = (quiz.W, quiz.H), q.thumbnail()
        default_seconds = q.tl.end
        frame_at = lambda t: q.render(t, duration)
        if art.get("teaser"):                   # 冒頭の場面へ戻る直前に、通常動画への案内を重ねる
            tz = art["teaser"]
            ov = teaser_overlay(tz["long"], tz["round"], tz["total"], q.tl.loop[0] if q.tl.loop else q.tl.end - 0.3)
            frame_at = lambda t: ov(q.render(t, duration).convert("RGBA"), t).convert("RGB")  # noqa: E731
    else:
        L = Layout(art, img, args.format)
        size, thumb = L.size, thumbnail(L)
        default_seconds = DEFAULT_SECONDS
        frame_at = lambda t: render_frame(L, t, duration)
    thumb.save(out / f"{stem}_thumb.png")
    img.save(out / f"{base}.jpg", quality=92)
    (out / f"{base}.json").write_text(json.dumps(art, ensure_ascii=False, indent=2))
    if style == "quiz" and art["quiz"].get("narration"):
        (out / f"{base}.txt").write_text("\n".join(v["text"] for v in art["quiz"]["narration"].values()) + "\n")
    else:
        (out / f"{base}.txt").write_text(script_text(art))
    if not args.still:
        duration = probe_duration(args.audio) + 1.0 if args.audio else (args.seconds or default_seconds)
        if style == "quiz":
            duration = q.tl.end
        print(f"動画を書き出しています({duration:.1f}秒)")
        render_video(size, frame_at, duration, out / f"{stem}.mp4", args.audio)
    if args.history and style == "quiz" and not args.still:
        number = len(history) + 1
        meta = youtube_meta(art, number, history)
        meta.update({"key": f"{art['source']}:{art['id']}", "number": number, "source": art["source"],
                     "artist": art.get("famous_artist") or art.get("artist"),
                     # variant: base = 顔のない絵 / portrait = 人物画(冒頭は顔以外)。stats.md で比べる(2026-11-26〜)
                     "variant": "hook" if args.hook else ("portrait" if art.get("has_face") else "base"),
                     "has_face": art.get("has_face"),
                     "ending": "loop_short",
                     # 冒頭の帯の版(header)か今まで通り(plain)か。stats.md の category で比べる(2026-11-28〜)
                     "category": "header" if header else "plain",
                     "format": "fashion" if fashion_item else ("ukiyoe" if art.get("ukiyoe") else "year"),
                     "teaser": teaser[0] if teaser else None,   # 予告編の回なら通常動画の番号   # 「服装から当てる」回(fashion.py)と比べる    # 冒頭の場面へ戻る終わり方+作品名を読み上げない短い版(2026-11-21〜)
                     "site": site_fields(art),
                     "id": art["id"], "date": today, "video": f"{stem}.mp4", "thumbnail": f"{stem}_thumb.png"})
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        print(f"投稿用: {meta['title']}")
    if record:
        used = load_used(used_path)
        used.append({"source": art["source"], "id": art["id"], "date": today, "title": art["title"]})
        used_path.write_text(json.dumps(used, ensure_ascii=False, indent=2))
    print(f"完了: {out / stem}")


if __name__ == "__main__":
    main()

"""浮世絵の回(2026-11-28〜)。浮世絵(江戸〜明治の木版画)を見て、作られた年を3択で当てる。

- UKIYOE_EVERY 本に1本(番号がその倍数の回)。服装の回(fashion.FASHION_EVERY の倍数)と重なったら、次の番号の回にずらす
- 作品はシカゴ美術館(AIC)のパブリックドメイン(CC0)の木版画。ARTISTS の絵師の本人の作品だけ
  (美術館のデータの作者 artist_title が名前と同じもの。「〜派」「〜の弟子」などは入らない)。
  2026-11-28 に検索の上位100件ずつを数えたところ、制作年の幅が10年以内のものが絵師ごとに18〜85点あった
- 版画は「描いた」ものではないので、題名・画面の問い・読み上げ・説明は「made」(作られた)にする
- 顔の大きく描かれた絵は見てもらいにくかったので、北斎・広重(風景・花鳥が多い)を多めに選び、
  候補を何点か見て顔のない作品を優先する(art_shorts.choose_famous と同じ考え方)
- 選択肢は 1680〜1910 年の中で、正解から25〜120年離した年(浮世絵どうしで見分けられる幅)
- 縦に極端に長い柱絵(hashira-e)・本・続き物(三枚続など)は、画面に収まりにくいので入れない
"""
import re

import art_shorts as A

UKIYOE_EVERY = 6

# (美術館のデータの作者名, 日本語の名前, 選ばれやすさ)。どの絵師も没後70年以上たっている
ARTISTS = [
    ("Katsushika Hokusai", "葛飾北斎", 3),
    ("Utagawa Hiroshige", "歌川広重", 3),
    ("Utagawa Kuniyoshi", "歌川国芳", 1),
    ("Kitagawa Utamaro", "喜多川歌麿", 1),
    ("Suzuki Harunobu", "鈴木春信", 1),
    ("Torii Kiyonaga", "鳥居清長", 1),
    ("Toshusai Sharaku", "東洲斎写楽", 1),
    ("Keisai Eisen", "渓斎英泉", 1),
    ("Tsukioka Yoshitoshi", "月岡芳年", 1),
]
JA_NAMES = {en: ja for en, ja, _ in ARTISTS}
FIELDS = A.AIC.FIELDS + ",thumbnail"
SKIP_MEDIUM = re.compile(r"hashira|diptych|triptych|polyptych|album|book", re.I)
TRIES = 6               # 顔のない作品を探す候補の数
MIN_YEAR, MAX_YEAR = 1680, 1910


def is_due(number):
    import fashion as F
    if number % UKIYOE_EVERY == 0:
        return not F.is_due(number)
    return number > 1 and (number - 1) % UKIYOE_EVERY == 0 and F.is_due(number - 1)


def short_title(t):
    """'Under the Wave off Kanagawa (Kanagawa oki nami ura), also known as ..., from the series "..."'
    → 'Under the Wave off Kanagawa'(画面に出す短い題名)。"""
    s = re.split(r",? from the series|, also known as", t)[0]
    s = re.sub(r"\s*\([^)]*\)", "", s).strip(" ,")
    return s or t


def _order(rng):
    names, pool = [], [(n, w) for n, _, w in ARTISTS]
    while pool:
        total = sum(w for _, w in pool)
        r = rng.uniform(0, total)
        for i, (n, w) in enumerate(pool):
            r -= w
            if r <= 0 or i == len(pool) - 1:
                names.append(n)
                pool.pop(i)
                break
    return names


def _search(src, name, page):
    import urllib.parse
    params = urllib.parse.urlencode({"q": name, "fields": FIELDS, "limit": 100, "page": page})
    data = A.http_json(f"{src.BASE}/artworks/search?{params}", A.AIC_LIMIT, src.headers)
    iiif = (data.get("config") or {}).get("iiif_url")
    if iiif:
        src.iiif_url = iiif.rstrip("/")
    return data.get("data") or [], int((data.get("pagination") or {}).get("total_pages") or 1)


def from_record(src, r, name):
    """AIC の記録 → 作品の dict(art_shorts.AIC.from_record と同じ形)。使えなければ None。"""
    import artists
    import quiz
    if (r.get("artist_title") or "").strip() != name or artists.is_attributed_only(r.get("artist_display") or ""):
        return None
    if (r.get("artwork_type_title") or "") != "Print" or "woodblock" not in (r.get("medium_display") or "").lower():
        return None
    if SKIP_MEDIUM.search(r.get("medium_display") or ""):
        return None
    th = r.get("thumbnail") or {}
    w, h = th.get("width"), th.get("height")
    if not w or not h or not 0.55 <= w / h <= 1.9:
        return None
    if r.get("is_public_domain") is not True or not r.get("image_id"):
        return None
    # 「c. 1820s」のように年代(10年単位)でしか分からない作品は、答えの年が決まらないので入れない
    if re.search(r"\d0s\b|possibly|probably|century|\?", r.get("date_display") or "", re.I):
        return None
    art = src.from_record({**r, "artwork_type_title": "Painting"})     # 絵画の判定だけを通す(版画として扱う)
    if not art or A.is_nude(art):          # 裸体の作品は出さない(art_shorts.is_nude)
        return None
    art["classification"] = "Print"
    art["artist"] = name
    # 答えの年は、美術館の表示(date_display)の最初の年にする。データの開始年(date_start)は
    # 表示より前のことがある(例: 表示「c.1830」、date_start 1825)。表示に年がなければ入れない
    m = re.search(r"\b(1[6-9]\d\d)\b", art.get("date") or "")
    if not m or art["year_start"] is None:
        return None
    y = int(m.group(1))
    if not art["year_start"] <= y <= (art["year_end"] or art["year_start"]):
        return None
    art["year_start"] = y
    if not quiz.accept(art) or not MIN_YEAR <= art["year_start"] <= MAX_YEAR - 10:
        return None
    art["title_full"] = art["title"]
    art["title"] = short_title(art["title"])
    art["famous_artist"] = name
    art["ukiyoe"] = True
    return art


def candidates(src, rng, used_ids):
    for name in _order(rng):
        records, pages = _search(src, name, 1)
        if pages >= 2:
            records += _search(src, name, 2)[0]
        rng.shuffle(records)
        n = 0
        for r in records:
            if str(r.get("id")) in used_ids:
                continue
            art = from_record(src, r, name)
            if art:
                yield art
                n += 1
                if n >= 2:            # 1人の絵師から2点まで(絵師がかたよらないように)
                    break


def choose(src, rng, used):
    """未使用の浮世絵を1点。顔のない作品を優先する。見つからなければ None。"""
    used_ids = {u["id"] for u in used if u.get("source") == "aic"}
    first = None
    for i, art in enumerate(candidates(src, rng, used_ids)):
        face = A.has_face(art)
        art["has_face"] = face
        print(f"  候補: {art['artist']} 「{art['title'][:40]}」 {art['date']} 顔{'あり' if face else ('なし' if face is False else '不明')}")
        if face is False:
            return art
        first = first or art
        if i + 1 >= TRIES:
            break
    return first


def choices(answer, rng):
    """(年3つ, 正解の位置)。外れは正解から25〜120年、外れ同士も25年以上離す。"""
    for _ in range(500):
        picks = [answer + rng.randint(25, 120) * rng.choice((-1, 1)) for _ in range(2)]
        ys = [answer] + picks
        if any(not MIN_YEAR <= y <= MAX_YEAR for y in picks):
            continue
        if min(abs(a - b) for i, a in enumerate(ys) for b in ys[i + 1:]) < 25:
            continue
        break
    else:
        ys = [answer, answer - 60, answer + 60] if answer + 60 <= MAX_YEAR else [answer, answer - 50, answer - 100]
    rng.shuffle(ys)
    return ys, ys.index(answer)

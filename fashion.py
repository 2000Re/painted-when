"""「服装から当てる」回(2026-11-21〜)。人物の服・襟・帽子などを手がかりに、描かれた世紀を3択で当てる。

- FASHION_EVERY 本に1本(番号がその倍数の回)、下の ITEMS から未使用の1点を出す。出し終えたら、ふつうの回だけに戻る
- 冒頭は顔を入れずに服だけを映す(顔が冒頭にある回は離れる人が多かった)。切り取り位置 crop は作品ごとに、
  冒頭のコマの一覧画像で、顔(quiz.detect_faces)に重ならず服の特徴が映ることを確かめて決めた
- 答えは世紀(「1600s」= 1600〜1699年)。美術館のデータの制作年(date_start)から決める。
  世紀の境目から10年以内の作品は、答えがあいまいになるので入れない
- clue(答えのあと画面に出す一文、読み上げない)は、服飾史で定説になっていることだけを書く。
  その絵に実際に描かれているもの(襟・帽子・袖など)についてだけ書く
- 画像はシカゴ美術館(AIC)のパブリックドメイン(CC0)の作品。白黒の画像しか取れない作品は入れない

crop: (中心の横位置 u, 上端 top, 幅 w)。どれも作品の幅・高さに対する割合。高さは画面と同じ 9:16 から決まる
(下にはみ出すときは幅を縮める)。
"""
FASHION_EVERY = 5
TOP_GAP = 0.03          # 顔の検出枠は顎の少し上で終わるので、crop の上端をこれだけ下げる(冒頭に顎が映らないように)

ITEMS = [
    # 1500年代
    dict(source="aic", id="87760", crop=(0.50, 0.45, 0.40),          # Cranach the Elder, Magdalena of Saxony, c. 1529
         clue="Clue: wide feathered hats and puffed, slashed sleeves were German fashion in the early 1500s"),
    dict(source="aic", id="93554", crop=(0.50, 0.27, 0.38),          # Hans Eworth, 1563
         clue="Clue: puffed sleeves with gold cuffs and a small neck ruffle, an early form of the ruff (mid-1500s)"),
    dict(source="aic", id="80540", crop=(0.50, 0.50, 0.35),          # Sánchez Coello, Don Juan of Austria, 1559–60
         clue="Clue: a small ruff and a doublet decorated with slits, men's fashion of the mid-1500s"),
    # 1600年代
    dict(source="aic", id="105945", crop=(0.50, 0.35, 0.45),         # Frans Hals, Portrait of a Lady, 1627
         clue="Clue: the huge “millstone” ruff, worn in the Dutch Republic in the early 1600s"),
    dict(source="aic", id="80539", crop=(0.50, 0.53, 0.34),          # Paulus Moreelse, c. 1620
         clue="Clue: a standing lace collar fanned out behind the head, high fashion in the early 1600s"),
    dict(source="aic", id="20887", crop=(0.50, 0.43, 0.38),          # Pieter Dubordieu, 1633–35
         clue="Clue: a wide flat collar, which began to replace the ruff around the 1630s"),
    dict(source="aic", id="16394", crop=(0.45, 0.31, 0.40),          # Caspar Netscher, 1680
         clue="Clue: long curls and a lace cravat, men's fashion of the late 1600s"),
    # 1700年代
    dict(source="aic", id="79765", crop=(0.50, 0.35, 0.40),          # John Wollaston, 1749–52
         clue="Clue: a silk gown with lace ruffles at the elbows, typical of women's dress in the 1700s"),
    dict(source="aic", id="70133", crop=(0.50, 0.42, 0.35),          # John Russell, 1767
         clue="Clue: a tricorn hat and a long embroidered waistcoat, menswear of the 1700s"),
    dict(source="aic", id="4791", crop=(0.50, 0.33, 0.45),           # George Romney, Mrs. Francis Russell, 1785–87
         clue="Clue: a huge brimmed hat and a white dress, fashionable in the 1780s"),
    # 1800年代
    dict(source="aic", id="111317", crop=(0.45, 0.36, 0.40),         # Ingres, Comte de Pastoret, 1823–26
         clue="Clue: a high collar and a black neckcloth, men's fashion of the early 1800s"),
    dict(source="aic", id="20686", crop=(0.50, 0.40, 0.40),          # Gérôme, Portrait of a Woman, 1851
         clue="Clue: hair parted in the middle and smoothed over the ears, the style of the 1840s and 1850s"),
    dict(source="aic", id="20684", crop=(0.62, 0.50, 0.12),          # Caillebotte, Paris Street; Rainy Day, 1877
         clue="Clue: top hats and long dark coats, city menswear of the 1800s"),
    dict(source="aic", id="27992", crop=(0.83, 0.30, 0.15),          # Seurat, A Sunday on La Grande Jatte, 1884–86
         clue="Clue: the bustle, which pushed skirts out at the back, the fashion of the 1880s"),
]


def key(item):
    return f"{item['source']}:{item['id']}"


def is_due(number):
    return number % FASHION_EVERY == 0


def pick(history, rng):
    """未使用の1点。直前の「服装」の回と同じ世紀は後回しにはしない(作品数が少ないので)。全部出したら None。"""
    used = {h.get("key") for h in history}
    fresh = [it for it in ITEMS if key(it) not in used]
    return rng.choice(fresh) if fresh else None


def century_start(year):
    """1627 → 1600(「1600s」)。"""
    return year // 100 * 100


def choices(year, rng):
    """(ラベル3つ, 正解の位置)。連続した3つの世紀で、正解の位置はばらばら。1500s〜1800s の範囲に収める。"""
    c = century_start(year)
    starts = [s for s in (c - 200, c - 100, c) if 1400 <= s and s + 200 <= 1900]
    s = rng.choice(starts or [c - 100])
    cs = [s, s + 100, s + 200]
    return [f"{x}s" for x in cs], cs.index(c)


def detail(item, img):
    """quiz.pick_detail と同じ形 (中心u, 中心v, 幅の割合, 高さの割合, 種類)。"""
    W, H = img.size
    u, top, w = item["crop"]
    top += TOP_GAP
    cw = w * W
    ch = cw * 16 / 9
    if top * H + ch > H * 0.99:              # 下にはみ出すときは、上端はそのままで幅を縮める(顔を入れないため)
        ch = H * 0.99 - top * H
        cw = ch * 9 / 16
    cx = min(max(u * W, cw / 2), W - cw / 2)
    return cx / W, (top * H + ch / 2) / H, cw / W, ch / H, "fashion"

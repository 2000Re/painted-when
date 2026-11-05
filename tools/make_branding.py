"""チャンネルのアイコンとバナーを作る(動画と同じ額縁・配色・フォント)。

使い方: python tools/make_branding.py [--out branding]
  icon.png   : アイコン 800x800(YouTube では円形に切り抜かれ、小さく表示される)
  banner.png : バナー 2560x1440(文字は、どの端末でも表示される中央 1546x423 に収める)

使う絵は、美術館の API でパブリックドメイン(CC0)と確認できたものだけ(下の WORKS)。
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import art_shorts as A  # noqa: E402
import quiz as Q  # noqa: E402

# (source, id, 切り抜く中心 u, v)
ICON_WORK = ("met", "436535", 0.45, 0.32)        # ゴッホ「Wheat Field with Cypresses」の空
WORKS = [
    ("met", "437926"),   # ヴァトー「Mezzetin」
    ("met", "436535"),   # ゴッホ「Wheat Field with Cypresses」
    ("aic", "27992"),    # スーラ「A Sunday on La Grande Jatte — 1884」
    ("aic", "16568"),    # モネ「Water Lilies」
]
BANNER_SIDE = (0, 2)     # 左右の額縁に入れる絵(WORKS の番号)。背景には4点すべてを使う
BG = (22, 19, 17)


def fetch(source, oid):
    src = A.SOURCES[source]()
    art = src.fetch(oid)
    if not art or art.get("license") != "CC0":
        raise SystemExit(f"{source}:{oid} はパブリックドメインの絵画として取得できません")
    print(f"  {art['title']} / {art['artist']}")
    return art, A.download_image(art)


def crop_at(img, u, v, w, h):
    """img の (u, v) を中心に、縦横比 w:h でなるべく大きく切り抜いて w×h にする。"""
    iw, ih = img.size
    k = min(iw / w, ih / h) * 0.55
    cw, ch = w * k, h * k
    # 縁の 8% には撮影時の余白や額が写りやすいので、そこを避ける
    mx, my = iw * 0.08, ih * 0.08
    x0 = min(max(mx, u * iw - cw / 2), iw - mx - cw)
    y0 = min(max(my, v * ih - ch / 2), ih - my - ch)
    return img.resize((w, h), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch))


def framed(img, inner_w, inner_h, border):
    """作品を額縁に入れ、影を付けた RGBA 画像。"""
    if img.size == (inner_w, inner_h):
        art = img
    else:
        # 縁を 1.5% 内側で切る(撮影時の余白を隠す)
        iw, ih = img.size
        art = img.resize((inner_w, inner_h), Image.LANCZOS, box=(iw * 0.015, ih * 0.015, iw * 0.985, ih * 0.985))
    fr = A.make_frame(inner_w, inner_h, border)
    pad = 40
    out = Image.new("RGBA", (fr.width + 2 * pad, fr.height + 2 * pad), (0, 0, 0, 0))
    out.alpha_composite(A.drop_shadow(fr.size, 10, 18, pad), (0, 0))
    out.paste(art, (pad + border, pad + border))
    out.alpha_composite(fr, (pad, pad))
    return out


def icon(path, img):
    size = 800
    canvas = Image.new("RGBA", (size, size), BG + (255,))
    # 背景:同じ絵をぼかして暗く
    canvas.alpha_composite(A.make_background(img, (size, size)).convert("RGBA"))
    # 円に切り抜かれても角が欠けないよう、額縁は円に内接する大きさより少し小さく
    inner, border = 470, 30
    art = crop_at(img, ICON_WORK[2], ICON_WORK[3], inner, inner)
    f = framed(art, inner, inner, border)
    canvas.alpha_composite(f, ((size - f.width) // 2, (size - f.height) // 2))
    # 大きな「?」(小さく表示されても読めるよう太字・影付き)
    q = Q.text_layer(["?"], A.font(A.SANS_BOLD, 400), Q.WHITE, size, shadow=230)
    canvas.alpha_composite(q, (0, (size - q.height) // 2 - 10))
    canvas.convert("RGB").save(path)
    print(path)


def banner(path, works):
    w, h = 2560, 1440
    canvas = Image.new("RGBA", (w, h), BG + (255,))
    # 背景:4点の絵を横に並べてぼかし、暗くする(テレビでは全体が見える)
    strip = Image.new("RGB", (w, h))
    for i, (_, img) in enumerate(works):
        x0, x1 = i * w // len(works), (i + 1) * w // len(works)
        strip.paste(A.cover(img, (x1 - x0, h)), (x0, 0))
    bg = strip.resize((w // 8, h // 8), Image.BILINEAR).filter(ImageFilter.GaussianBlur(5))
    bg = bg.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(8))
    arr = np.asarray(bg).astype(np.float32) * 0.36
    yy = np.abs(np.arange(h) - h / 2)[:, None] / (h / 2)
    arr *= (1 - 0.5 * np.clip(yy - 0.15, 0, 1))[..., None]
    canvas.alpha_composite(Image.fromarray(arr.astype(np.uint8)).convert("RGBA"))

    # 額縁に入った絵を左右に1点ずつ(パソコンでは見え、スマホでは中央の文字だけになる)
    safe_w, safe_h = 1546, 423
    sx0, sx1 = (w - safe_w) // 2, (w + safe_w) // 2
    cy = h // 2
    side = [works[i] for i in BANNER_SIDE]
    for cx, (art, img) in zip((sx0 // 2, (sx1 + w) // 2), side):
        iw, ih = img.size
        inner_h = 300
        inner_w = int(inner_h * iw / ih)
        if inner_w > 360:
            inner_w = 360
            inner_h = int(inner_w * ih / iw)
        f = framed(img, inner_w, inner_h, 14)
        canvas.alpha_composite(f, (int(cx - f.width / 2), int(cy - f.height / 2)))

    # 中央:チャンネル名と一言、動画と同じ形の選択肢
    title = Q.text_layer(["Painted When?"], A.font(A.SERIF_IT, 150), Q.WHITE, safe_w, shadow=220)
    tag = Q.text_layer(["A daily art quiz  ·  Guess the year"], A.font(A.SANS_BOLD, 40), Q.GOLD, safe_w)
    labels = ["1803", "1884", "1951"]   # 真ん中が正解(右の額縁のスーラ「グランド・ジャット島」は1884〜86年)
    f_choice = A.font(A.SANS_BOLD, 40)
    pills = [Q.pill(lb, f_choice, Q.GOLD + (255,), (25, 20, 10)) if i == 1 else
             Q.pill(lb, f_choice, (20, 20, 24, 215), Q.WHITE, outline=(255, 255, 255, 120))
             for i, lb in enumerate(labels)]
    top = cy - safe_h // 2 + 8
    canvas.alpha_composite(title, (sx0, top))
    canvas.alpha_composite(tag, (sx0, top + title.height - 10))
    pw = pills[0].width
    gap = 6
    px0 = int(w / 2 - (3 * pw + 2 * gap) / 2)
    py = top + title.height + tag.height + 4
    for i, p in enumerate(pills):
        canvas.alpha_composite(p, (px0 + i * (pw + gap), py))
    assert py + pills[0].height <= cy + safe_h // 2, "文字が中央の安全範囲からはみ出しています"
    canvas.convert("RGB").save(path)
    print(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "branding"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print("絵を取得しています")
    fetched = {(s, i): fetch(s, i) for s, i in WORKS}
    icon(out / "icon.png", fetched[ICON_WORK[:2]][1])
    banner(out / "banner.png", [fetched[k] for k in WORKS])


if __name__ == "__main__":
    main()

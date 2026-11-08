"""「When was this painted?」の3択クイズ形式の縦型動画(Shorts)。

流れ(秒は既定の13秒の場合):
  0.0〜  絵の一部(顔があれば顔、なければ目立つところ)を画面いっぱいに映し、問いを出す
  0.5〜3.2  引いていき、額縁に収まった全体を見せる
  3.0〜  3択が出る。4.0〜8.0 は残り時間のバーが減っていく
  8.2   正解の選択肢が光る
  8.8〜  題名・作者・年(美術館の表記)・技法
冒頭はフェードインせず、いきなり絵から始める(Shorts はループ再生されるため最後もフェードしない)。
"""
import math
import os
from pathlib import Path
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import art_shorts as A

W, H = 1080, 1920
DEFAULT_SECONDS = 13.0
MAX_SPAN = 10          # 制作年の幅(終了−開始)がこれ以内の作品だけクイズにする

class Timeline:
    """各場面の始まる時刻(秒)。ナレーションがあるときは、声の長さから narration.py が決める。"""

    def __init__(self, pull=(0.5, 3.2), choices=(3.0, 3.35, 3.7), timer=(4.0, 8.0), reveal=8.2,
                 info=(8.8, 9.3, 9.8), outro=None, end=DEFAULT_SECONDS):
        self.pull = pull          # 引いていく区間
        self.choices = choices    # 選択肢が1つずつ出る時刻
        self.timer = timer        # 残り時間のバー
        self.reveal = reveal      # 正解が光る
        self.info = info          # 題名・作者・年と技法
        self.outro = outro        # 上の問いが「How did you do?」に変わる(None なら変えない)
        self.end = end            # 動画の長さ

    def as_dict(self):
        r = lambda v: [round(x, 2) for x in v] if isinstance(v, (tuple, list)) else (None if v is None else round(v, 2))
        return {k: r(v) for k, v in vars(self).items()}

# 画面の配置(1080x1920)。下部 約430px と右端 約150px(y 900 以降)は YouTube の表示が重なる
FRAME_BOX = (60, 290, 1020, 1110)      # 額縁を含めた作品の置き場所
CHOICE_Y = 1196                        # 選択肢の中心
CHOICE_W, CHOICE_H, CHOICE_GAP = 240, 96, 22
CHOICE_CX = 505                        # 右側のボタンを避けて少し左に寄せる
TIMER_Y = 1262
INFO_Y = 1290                          # 題名の上端
TEXT_X, TEXT_W = 90, 800

GOLD = (236, 200, 120)
WHITE = (250, 246, 236)


# ---------------------------------------------------------------- 問題


def quiz_year(art):
    """クイズの正解にする年。制作年の幅が大きすぎる作品は None。"""
    a, b = art.get("year_start"), art.get("year_end")
    if a is None:
        return None
    b = a if b is None else b
    if b < a or b - a > MAX_SPAN:
        return None
    if a == 0 and b == 0:      # 年が不明な記録は 0 のことがある
        return None
    return a


def accept(art):
    return quiz_year(art) is not None


def year_label(y, with_ad=False):
    if y < 0:
        return f"{-y} BC"
    return f"AD {y}" if with_ad else str(y)


def choice_labels(ys):
    """紀元前が混ざるときだけ、紀元後に AD を付ける。"""
    bc = any(y < 0 for y in ys)
    return [year_label(y, with_ad=bc) for y in ys]


def make_choices(answer, rng, max_year):
    """正解と、もっともらしい外れ2つを並べる。外れは正解から離し、外れ同士も離す。"""
    if answer >= 1500:
        lo, hi = 45, 220
    elif answer >= 1000:
        lo, hi = 80, 350
    else:
        lo, hi = 150, 600
    floor = -1500
    for _ in range(500):
        picks = []
        for _ in range(2):
            d = rng.randint(lo, hi) * rng.choice((-1, 1))
            picks.append(answer + d)
        ys = [answer] + picks
        if any(y > max_year or y < floor for y in picks):
            continue
        if min(abs(a - b) for i, a in enumerate(ys) for b in ys[i + 1:]) < lo * 0.8:
            continue
        # 紀元前と紀元後をまたぐ「0年」は避ける
        if 0 in picks:
            continue
        break
    else:
        picks = [answer - 2 * hi, answer - hi] if answer - 2 * hi > floor else [answer + hi, answer + 2 * hi]
    ys = [answer] + picks
    rng.shuffle(ys)
    return ys, ys.index(answer)


# ---------------------------------------------------------------- 冒頭で拡大する場所


FACE_MODEL = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
FACE_SHARE = 0.38       # 顔が、拡大範囲の幅のこのくらいを占めるように映す
MAX_CROP_FRAC = 0.6     # 顔が大きい肖像画でも、作品の幅のこれ以下に拡大する


def detect_faces(img, score_threshold=0.7):
    """作品の中の顔(OpenCV の YuNet)。返り値は [(左, 上, 幅, 高さ, 確からしさ)](0〜1 の割合)。
    OpenCV やモデルがなければ空(そのときは目立つ部分で選ぶ)。"""
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")   # 実害のない警告を出さない
    try:
        import cv2
    except ImportError:
        return []
    if not FACE_MODEL.exists():
        return []
    small = img.convert("RGB")
    small.thumbnail((1024, 1024))
    arr = np.ascontiguousarray(np.asarray(small)[:, :, ::-1])
    h, w = arr.shape[:2]
    det = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (w, h), score_threshold, 0.3, 50)
    _, faces = det.detect(arr)
    if faces is None:
        return []
    return [(f[0] / w, f[1] / h, f[2] / w, f[3] / h, float(f[14])) for f in faces]


def _norm(a):
    a = a - a.min()
    m = a.max()
    return a / m if m > 0 else a


def _blur(a, r):
    """0〜1 に正規化してぼかす(Pillow のぼかしは 8bit 画像だけなので、一度 0〜255 にする)。"""
    im = Image.fromarray((_norm(np.asarray(a, np.float64)) * 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), np.float32) / 255


def saliency(img, size):
    """目立つ部分の地図(size=(幅, 高さ)、0〜1)。周りと違うところ(spectral residual)・色の鮮やかさ・模様の細かさを合わせる。"""
    w, h = size
    g = np.asarray(img.convert("L").resize((128, max(8, int(128 * h / w))), Image.BILINEAR), dtype=np.float64)
    f = np.fft.fft2(g)
    log_amp = np.log(np.abs(f) + 1e-9)
    k = np.ones((3, 3)) / 9
    avg = np.real(np.fft.ifft2(np.fft.fft2(log_amp) * np.fft.fft2(k, log_amp.shape)))
    sr = np.abs(np.fft.ifft2(np.exp(log_amp - avg + 1j * np.angle(f)))) ** 2
    sr = _blur(sr, 2.5)
    sr = np.asarray(Image.fromarray((sr * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR), np.float32) / 255
    hsv = np.asarray(img.convert("HSV").resize((w, h), Image.BILINEAR), dtype=np.float32) / 255
    sat = _blur(hsv[:, :, 1] * (0.3 + 0.7 * hsv[:, :, 2]), 3)
    lum = np.asarray(img.convert("L").resize((w, h), Image.BILINEAR), dtype=np.float32)
    gy, gx = np.gradient(lum)
    edge = _blur(np.hypot(gx, gy), 2)
    return 0.5 * _norm(sr) + 0.3 * _norm(sat) + 0.2 * _norm(edge)


def _crop_size(w, h, cw, margin_x, margin_y):
    """幅 cw(画素)・縦横 9:16 の範囲を、作品の縁を除いた中に収まるよう縮める。"""
    ch = cw * 16 / 9
    if ch > h - 2 * margin_y:
        ch = h - 2 * margin_y
        cw = ch * 9 / 16
    if cw > w - 2 * margin_x:
        cw = w - 2 * margin_x
        ch = cw * 16 / 9
    return max(4.0, cw), max(4.0, ch)


def pick_detail(img, crop_frac_w, rng, faces=None):
    """冒頭で拡大する場所を選ぶ。返り値は (中心u, 中心v, 幅の割合, 高さの割合, 種類)。u〜高さは 0〜1。
    範囲は画面と同じ 9:16 で、作品の縁(額や撮影時の余白が写りやすい)を避ける。
    1. 顔があれば、いちばん目立つ顔(大きさ・確からしさ・中央寄り)を、範囲の上寄りに大きく映す
    2. なければ、目立つ部分(saliency)がいちばん多く入る範囲"""
    W, H = img.size
    margin_x, margin_y = W * 0.07, H * 0.07
    faces = detect_faces(img) if faces is None else faces
    # 小さすぎる顔(群衆の中の顔など)は使わない
    faces = [f for f in faces if f[2] * W >= 0.05 * min(W, H)]
    if faces:
        def face_score(f):
            x, y, fw, fh, sc = f
            cx, cy = x + fw / 2 - 0.5, y + fh / 2 - 0.5
            return sc * math.sqrt(fw * fh) * (1 - 0.5 * math.hypot(cx, cy))
        x, y, fw, fh, _ = max(faces, key=face_score)
        frac = min(max(fw / FACE_SHARE, crop_frac_w), MAX_CROP_FRAC)
        cw, ch = _crop_size(W, H, frac * W, margin_x, margin_y)
        cx = (x + fw / 2) * W
        cy = (y + fh / 2) * H + ch * 0.12      # 顔が範囲の上寄り(目の高さが上から3分の1あたり)に来るように
        cx = min(max(cx, margin_x + cw / 2), W - margin_x - cw / 2)
        cy = min(max(cy, margin_y + ch / 2), H - margin_y - ch / 2)
        return float(cx / W), float(cy / H), float(cw / W), float(ch / H), "face"

    sw, sh = (480, max(8, int(480 * H / W))) if W >= H else (max(8, int(480 * W / H)), 480)
    sal = saliency(img, (sw, sh))
    k = sw / W
    cw, ch = _crop_size(sw, sh, crop_frac_w * sw, margin_x * k, margin_y * k)
    cw, ch = int(round(cw)), int(round(ch))
    mx, my = int(margin_x * k), int(margin_y * k)
    ii = np.pad(sal.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    best, best_xy = -1, (sw // 2 - cw // 2, sh // 2 - ch // 2)
    for y0 in range(my, max(my + 1, sh - my - ch + 1), 3):
        for x0 in range(mx, max(mx + 1, sw - mx - cw + 1), 3):
            s = ii[y0 + ch, x0 + cw] - ii[y0, x0 + cw] - ii[y0 + ch, x0] + ii[y0, x0]
            cx, cy = (x0 + cw / 2) / sw - 0.5, (y0 + ch / 2) / sh - 0.5
            s *= 1 - 0.4 * math.hypot(cx, cy)   # 中央寄りを少し優先
            if s > best:
                best, best_xy = s, (x0, y0)
    x0, y0 = best_xy
    return (x0 + cw / 2) / sw, (y0 + ch / 2) / sh, cw / sw, ch / sh, "salient"


# ---------------------------------------------------------------- 部品


def text_layer(lines, fnt, fill, width, align="center", spacing=1.18, shadow=200):
    lh = int(fnt.size * spacing)
    layer = Image.new("RGBA", (width, lh * len(lines) + 12), (0, 0, 0, 0))
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(layer), ImageDraw.Draw(sh)
    x = width / 2 if align == "center" else 0
    anchor = "ms" if align == "center" else "ls"
    for i, ln in enumerate(lines):
        y = i * lh + int(lh * 0.8)
        ds.text((x, y + 3), ln, font=fnt, fill=(0, 0, 0, shadow), anchor=anchor)
        d.text((x, y), ln, font=fnt, fill=fill, anchor=anchor)
    out = sh.filter(ImageFilter.GaussianBlur(5))
    out.alpha_composite(layer)
    return out


def with_alpha(layer, a):
    if a >= 1:
        return layer
    out = layer.copy()
    out.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
    return out


def pill(label, fnt, fill, text_fill, outline=None):
    im = Image.new("RGBA", (CHOICE_W + 20, CHOICE_H + 20), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([10, 14, 10 + CHOICE_W, 14 + CHOICE_H], radius=CHOICE_H // 2,
                                         fill=(0, 0, 0, 150))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([10, 10, 10 + CHOICE_W, 10 + CHOICE_H], radius=CHOICE_H // 2, fill=fill,
                        outline=outline, width=3 if outline else 0)
    d.text((10 + CHOICE_W / 2, 10 + CHOICE_H / 2), label, font=fnt, fill=text_fill, anchor="mm")
    return im


def lerp(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------------- レイアウトと描画


class Quiz:
    def __init__(self, art, img, rng, max_year, timeline=None):
        self.art = art
        self.tl = timeline or Timeline()
        self.answer = quiz_year(art)
        if self.answer is None:
            raise ValueError("この作品には、クイズに使える制作年がありません")
        self.choices, self.correct = make_choices(self.answer, rng, max_year)

        self.bg = A.make_background(img, (W, H)).convert("RGBA")
        # 上部を暗くして問いを読みやすくする(拡大中は作品の上に重なる)
        grad = np.zeros((H, W), np.float32)
        top = np.linspace(0.62, 0, 430)
        grad[:430] = top[:, None]
        self.top_shade = Image.fromarray((grad * 255).astype(np.uint8), "L")
        self.top_shade = Image.merge("RGBA", [Image.new("L", (W, H), 0)] * 3 + [self.top_shade])

        # 額縁に収めたときの作品の位置
        self.border = 24
        bx0, by0, bx1, by1 = FRAME_BOX
        iw, ih = A.frame_dims(img, bx1 - bx0, by1 - by0, self.border)
        self.inner = (iw, ih)
        fw, fh = iw + 2 * self.border, ih + 2 * self.border
        fx, fy = bx0 + (bx1 - bx0 - fw) // 2, by0 + (by1 - by0 - fh) // 2
        self.final_rect = (fx + self.border, fy + self.border, iw, ih)
        self.frame = A.make_frame(iw, ih, self.border)
        self.frame_xy = (fx, fy)
        self.shadow_pad = 40
        self.shadow = A.drop_shadow(self.frame.size, 10, 18, self.shadow_pad)

        # 冒頭の拡大:画像の画素が足りる範囲で、作品の幅の 22% 前後を画面いっぱいに
        sw, shh = img.size
        crop_frac = max(0.22, (W / 2.4) / sw)
        *self.detail, self.detail_kind = pick_detail(img, min(crop_frac, 0.9), rng)
        # 縮小した画像を何段か用意し、表示の大きさに近いものから切り出す(毎フレームの処理を軽くする)
        self.pyramid = [img]
        while max(self.pyramid[-1].size) > 900:
            p = self.pyramid[-1]
            self.pyramid.append(p.resize((p.width // 2, p.height // 2), Image.LANCZOS))

        # 文字
        self.q_kicker = text_layer(["TODAY'S ART QUIZ"], A.font(A.SANS_BOLD, 30), GOLD, W)
        self.q_main = text_layer(["When was this painted?"], A.font(A.SANS_BOLD, 66), WHITE, W)
        self.q_outro = text_layer(["How did you do?"], A.font(A.SANS_BOLD, 66), WHITE, W)
        credit = f"{art['museum']} · Public Domain (CC0)"
        self.credit = text_layer([credit], A.font(A.SANS, 24), (215, 210, 200, 230), W, shadow=160)
        f_choice = A.font(A.SANS_BOLD, 46)
        self.labels = choice_labels(self.choices)
        self.pills = [pill(lb, f_choice, (20, 20, 24, 215), WHITE, outline=(255, 255, 255, 120))
                      for lb in self.labels]
        self.pill_right = pill(self.labels[self.correct], f_choice, GOLD + (255,), (25, 20, 10))

        f_title, title_lines = A.fit_title(art["title"], A.SERIF_IT, TEXT_W, [54, 48, 42], 2)
        self.info = [
            text_layer(title_lines, f_title, WHITE, TEXT_W, align="left", spacing=1.12),
            text_layer(A.wrap(art["artist"], A.font(A.SERIF, 38), TEXT_W, 1), A.font(A.SERIF, 38),
                       GOLD + (255,), TEXT_W, align="left"),
        ]
        meta = " · ".join(x for x in (art.get("date"), art.get("medium")) if x)
        if meta:
            f = A.font(A.SERIF, 30)
            self.info.append(text_layer(A.wrap(meta, f, TEXT_W, 1), f, (220, 214, 204, 255), TEXT_W,
                                        align="left"))
        self.info_y = []
        y = INFO_Y
        for i, layer in enumerate(self.info):
            self.info_y.append(y)
            y += layer.height - 12 + (6 if i == 0 else 2)

    # 作品の表示位置(画面座標の矩形)
    def art_rect(self, t):
        u, v, dw, dh = self.detail
        fx, fy, fw, fh = self.final_rect
        p0, p1 = self.tl.pull
        e = A.ease((t - p0) / (p1 - p0))
        # 開始:拡大範囲が画面を覆う大きさ。少しずつ引き始める(0〜0.5秒もわずかに動かす)
        w0 = max(W / dw, H / dh * (fw / fh))
        w0 *= 1.06 - 0.06 * min(1.0, max(0.0, t) / p0)
        w = math.exp(lerp(math.log(w0), math.log(fw), e))
        h = w * fh / fw
        # 拡大中心 (u,v) が、画面中央から最終位置へ移る
        px = lerp(W / 2, fx + u * fw, e)
        py = lerp(H / 2, fy + v * fh, e)
        return px - u * w, py - v * h, w, h, e

    def draw_art(self, frame, rect):
        x, y, w, h = rect
        x0, y0 = max(0.0, x), max(0.0, y)
        x1, y1 = min(float(W), x + w), min(float(H), y + h)
        if x1 - x0 < 1 or y1 - y0 < 1:
            return
        # 表示倍率に合う段を選ぶ(元画像の画素が表示の2倍以下になる最小の段)
        src = self.pyramid[0]
        for p in self.pyramid:
            if p.width >= w:
                src = p
        k = src.width / w
        box = (max(0.0, (x0 - x) * k), max(0.0, (y0 - y) * k),
               min(float(src.width), (x1 - x) * k), min(float(src.height), (y1 - y) * k))
        ox, oy = int(math.floor(x0)), int(math.floor(y0))
        size = (int(math.ceil(x1)) - ox, int(math.ceil(y1)) - oy)
        piece = src.resize(size, Image.BICUBIC, box=box)
        frame.paste(piece, (ox, oy))

    def render(self, t, duration):
        frame = self.bg.copy()
        x, y, w, h, e = self.art_rect(t)
        fw = self.final_rect[2]
        scale = w / fw
        # 額縁と影は、引き終わりに近づいてから出す
        fa = A.ease((e - 0.55) / 0.45)
        if fa > 0:
            b = self.border * scale
            size = (int(round(w + 2 * b)), int(round(h + 2 * b)))
            sh = self.shadow.resize((int(self.shadow.width * scale), int(self.shadow.height * scale)), Image.BILINEAR)
            frame.alpha_composite(with_alpha(sh, fa), (int(x - b - self.shadow_pad * scale),
                                                        int(y - b - self.shadow_pad * scale)))
        self.draw_art(frame, (x, y, w, h))
        if fa > 0:
            b = self.border * scale
            fr = self.frame if abs(scale - 1) < 1e-3 else self.frame.resize(
                (int(round(w + 2 * b)), int(round(h + 2 * b))), Image.BILINEAR)
            frame.alpha_composite(with_alpha(fr, fa), (int(round(x - b)), int(round(y - b))))
        frame.alpha_composite(self.top_shade)

        # 問い
        tl = self.tl
        oa = A.ease((t - tl.outro) / 0.4) if tl.outro is not None else 0
        frame.alpha_composite(self.q_kicker, (0, 130))
        if oa < 1:
            frame.alpha_composite(with_alpha(self.q_main, 1 - oa), (0, 178))
        if oa > 0:
            frame.alpha_composite(with_alpha(self.q_outro, oa), (0, 178))
        # 出典(引き終わってから額縁の下に)
        ca = A.ease((t - tl.pull[1]) / 0.4)
        if ca > 0:
            fy_bottom = self.frame_xy[1] + self.frame.height
            frame.alpha_composite(with_alpha(self.credit, ca), (0, fy_bottom + 2))

        # 選択肢
        n = len(self.choices)
        total = n * CHOICE_W + (n - 1) * CHOICE_GAP
        for i, p in enumerate(self.pills):
            a = A.ease((t - tl.choices[i]) / 0.3)
            if a <= 0:
                continue
            px = int(CHOICE_CX - total / 2 + i * (CHOICE_W + CHOICE_GAP)) - 10
            py = CHOICE_Y - CHOICE_H // 2 - 10 + int((1 - a) * 30)
            r = A.ease((t - tl.reveal) / 0.3)
            if i == self.correct and r > 0:
                frame.alpha_composite(with_alpha(p, a * (1 - r)), (px, py))
                pop = 1 + 0.08 * math.sin(math.pi * min(1.0, (t - tl.reveal) / 0.5))
                pr = self.pill_right
                if pop != 1:
                    pr = pr.resize((int(pr.width * pop), int(pr.height * pop)), Image.BICUBIC)
                frame.alpha_composite(with_alpha(pr, r), (px - (pr.width - p.width) // 2,
                                                          py - (pr.height - p.height) // 2))
            else:
                frame.alpha_composite(with_alpha(p, a * (1 - 0.65 * r)), (px, py))

        # 残り時間のバー
        ta = A.ease((t - tl.timer[0] + 0.3) / 0.3) * (1 - A.ease((t - tl.reveal) / 0.3))
        if ta > 0:
            left = 1 - min(1.0, max(0.0, (t - tl.timer[0]) / (tl.timer[1] - tl.timer[0])))
            bx0 = int(CHOICE_CX - total / 2)
            d = ImageDraw.Draw(frame)
            d.rounded_rectangle([bx0, TIMER_Y, bx0 + total, TIMER_Y + 8], radius=4,
                                fill=(255, 255, 255, int(60 * ta)))
            if left > 0:
                col = GOLD if left > 0.3 else (235, 110, 90)
                d.rounded_rectangle([bx0, TIMER_Y, bx0 + max(8, int(total * left)), TIMER_Y + 8], radius=4,
                                    fill=col + (int(255 * ta),))

        # 答え合わせ:題名・作者・年
        for i, layer in enumerate(self.info):
            a = A.ease((t - tl.info[i]) / 0.6)
            if a > 0:
                frame.alpha_composite(with_alpha(layer, a), (TEXT_X, self.info_y[i] - 8))
        return frame.convert("RGB")

    def thumbnail(self):
        """サムネ:選択肢が出そろい、答えはまだの状態。"""
        return self.render((self.tl.timer[0] + self.tl.timer[1]) / 2, self.tl.end)

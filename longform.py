"""通常動画(横 1920x1080)「Art History Timeline Challenge」を作る。週1本、10問。

Shorts と同じ美術館のオープンデータ(パブリックドメインの作品だけ)・有名な画家のリスト・3択の作り方・声を使い、
横長の画面用に組み直したもの。右に額縁に入った作品、左の帯に問題・3択・残り時間を出す。

  0:00  導入  「Welcome to the Art History Timeline Challenge! 10 paintings, 5 seconds each. Keep score!」
  各問  作品の一部から引いて全体を見せる → 「Was it A, B, or C?」→ 5秒 → 正解の年と、題名・作者・年・技法
  最後  10点を制作年の順に年表に並べ、何年分の美術史だったかを見せる。点数の目安

答え(年)と説明は美術館のデータ(と timeline_facts.py の教科書にのる出来事)だけで作る。
チャプターは「Painting 1」などにして、答えは書かない(答えは説明欄の下の方にまとめる)。

使い方:
  python longform.py --tts dummy --rounds 3 --source aic --out out_long   試し(仮の声・3問・シカゴ美術館だけ)
  python longform.py --history longform_history.json --out out_long       本番(meta.json も書く)
  python longform.py --upload --dir out_long --privacy unlisted           投稿して longform_history.json に記録
"""
import argparse
import json
import math
import random
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw

import art_shorts as A
import narration as N
import quiz as Q
import timeline_facts

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "longform_history.json"
SHORTS_HISTORY = ROOT / "upload_history.json"
TZ = ZoneInfo("Asia/Tokyo")
W, H, FPS = 1920, 1080, 30
SR = N.SR
ROUNDS = 10
THINK = 5.0
MIN_CHAPTER = 11.0              # YouTube のチャプターは1つ10秒以上
PANEL_W = 620
ART_BOX = (PANEL_W + 50, 50, W - 50, H - 90)     # 額縁を含めた作品の置き場所
NAVY = (14, 12, 18)
GOLD, WHITE = Q.GOLD, Q.WHITE
CHANNEL = "https://www.youtube.com/@painted-when"
SITE = "https://2000re.github.io/painted-when"
TITLE = "ART HISTORY TIMELINE"
PER_CENTURY = 3                 # 1つの世紀から出す作品の数の上限(時代がかたよらないように)


# ---------------------------------------------------------------- 画面の部品


def font(size, bold=True, serif=False, italic=False):
    path = A.SERIF_IT if italic else A.SERIF if serif else A.SANS_BOLD if bold else A.SANS
    return A.font(path, size)


def text(lines, fnt, fill, width=PANEL_W, spacing=1.15, shadow=200):
    return Q.text_layer(lines, fnt, fill, width, spacing=spacing, shadow=shadow)


def wrap(s, fnt, max_w, max_lines=3):
    return A.wrap(s, fnt, max_w, max_lines)


def chrome(img, no=None, total=ROUNDS, credit=None):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, PANEL_W, H], fill=NAVY + (255,))
    d.text((PANEL_W / 2, 64), TITLE, font=font(30), fill=GOLD + (255,), anchor="mm")
    if no:
        d.text((PANEL_W / 2, 118), f"PAINTING {no} / {total}", font=font(40), fill=WHITE + (255,), anchor="mm")
        x0 = PANEL_W / 2 - (total - 1) * 24 / 2
        for k in range(total):
            c = GOLD if k < no else (70, 70, 84)
            d.ellipse([x0 + k * 24 - 6, 156 - 6, x0 + k * 24 + 6, 156 + 6], fill=c + (255,))
    if credit is not None:
        img.alpha_composite(credit, (PANEL_W, H - 50))


def countdown(img, t, start, end, y=640):
    if not (start <= t < end + 0.3):
        return
    a = 1 - A.ease((t - end) / 0.3)
    left = max(0.0, end - t)
    d = ImageDraw.Draw(img)
    n = math.ceil(left) if left > 0 else 0
    if n:
        d.text((PANEL_W / 2, y), str(n), font=font(120), fill=GOLD + (int(255 * a),), anchor="mm",
               stroke_width=5, stroke_fill=NAVY + (255,))
    x0, x1, yb = 90, PANEL_W - 90, y + 95
    d.rounded_rectangle([x0, yb, x1, yb + 10], radius=5, fill=(255, 255, 255, int(60 * a)))
    frac = left / (end - start)
    if frac > 0:
        col = GOLD if frac > 0.3 else (235, 110, 90)
        d.rounded_rectangle([x0, yb, x0 + max(10, int((x1 - x0) * frac)), yb + 10], radius=5, fill=col + (int(255 * a),))


def info_box(art, fact):
    """答えのあとの説明(題名・作者・年と技法・出来事との比較)。"""
    tw = PANEL_W - 110
    f_title = font(42, italic=True)
    layers = [text(wrap(art["title"], f_title, tw, 2), f_title, WHITE + (255,), spacing=1.1),
              text(wrap(art["artist"], font(32, serif=True), tw, 1), font(32, serif=True), GOLD + (255,))]
    meta = " · ".join(x for x in (art.get("date"), art.get("medium")) if x)
    if meta:
        layers.append(text(wrap(meta, font(26, serif=True), tw, 2), font(26, serif=True), (220, 214, 204, 255)))
    if fact:
        layers.append(text(wrap(fact, font(26), tw, 2), font(26), GOLD + (255,)))
    hgt = sum(x.height for x in layers) + 40
    box = Image.new("RGBA", (W, hgt + 10), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle([36, 0, PANEL_W - 36, hgt], radius=20, fill=(30, 26, 36, 240),
                                          outline=GOLD + (200,), width=3)
    y = 18
    for x in layers:
        box.alpha_composite(x, (0, y))
        y += x.height - 4
    return box


# ---------------------------------------------------------------- 作品の表示(額縁・冒頭の拡大)


class Canvas:
    def __init__(self, img, rng):
        self.bg = A.make_background(img, (W, H)).convert("RGBA")
        self.border = 22
        bx0, by0, bx1, by1 = ART_BOX
        iw, ih = A.frame_dims(img, bx1 - bx0, by1 - by0, self.border)
        fw, fh = iw + 2 * self.border, ih + 2 * self.border
        fx, fy = bx0 + (bx1 - bx0 - fw) // 2, by0 + (by1 - by0 - fh) // 2
        self.final = (fx + self.border, fy + self.border, iw, ih)
        self.frame = A.make_frame(iw, ih, self.border)
        self.frame_xy = (fx, fy)
        self.pad = 40
        self.shadow = A.drop_shadow(self.frame.size, 10, 18, self.pad)
        sw = img.size[0]
        crop_frac = max(0.25, ((W - PANEL_W) / 2.4) / sw)
        self.detail = Q.pick_detail(img, min(crop_frac, 0.9), rng)[:4]
        self.pyramid = [img]
        while max(self.pyramid[-1].size) > 900:
            p = self.pyramid[-1]
            self.pyramid.append(p.resize((p.width // 2, p.height // 2), Image.LANCZOS))

    def rect(self, e):
        """e=0: 冒頭の拡大(作品の一部が右の範囲いっぱい)、e=1: 額縁に収まった全体。"""
        u, v, dw, dh = self.detail
        fx, fy, fw, fh = self.final
        aw, ah = W - PANEL_W, H
        w0 = max(aw / dw, ah / dh * (fw / fh))
        w = math.exp(math.log(w0) + (math.log(fw) - math.log(w0)) * e)
        h = w * fh / fw
        cx0 = PANEL_W + aw / 2
        px = cx0 + (fx + u * fw - cx0) * e
        py = H / 2 + (fy + v * fh - H / 2) * e
        return px - u * w, py - v * h, w, h

    def draw(self, img, e):
        x, y, w, h = self.rect(e)
        scale = w / self.final[2]
        fa = A.ease((e - 0.55) / 0.45)
        if fa > 0:
            b = self.border * scale
            sh = self.shadow.resize((int(self.shadow.width * scale), int(self.shadow.height * scale)), Image.BILINEAR)
            img.alpha_composite(Q.with_alpha(sh, fa), (int(x - b - self.pad * scale), int(y - b - self.pad * scale)))
        x0, y0 = max(float(PANEL_W), x), max(0.0, y)
        x1, y1 = min(float(W), x + w), min(float(H), y + h)
        if x1 - x0 >= 1 and y1 - y0 >= 1:
            src = self.pyramid[0]
            for p in self.pyramid:
                if p.width >= w:
                    src = p
            k = src.width / w
            box = (max(0.0, (x0 - x) * k), max(0.0, (y0 - y) * k), min(float(src.width), (x1 - x) * k),
                   min(float(src.height), (y1 - y) * k))
            ox, oy = int(math.floor(x0)), int(math.floor(y0))
            img.paste(src.resize((int(math.ceil(x1)) - ox, int(math.ceil(y1)) - oy), Image.BICUBIC, box=box), (ox, oy))
        if fa > 0:
            b = self.border * scale
            fr = self.frame if abs(scale - 1) < 1e-3 else self.frame.resize(
                (int(round(w + 2 * b)), int(round(h + 2 * b))), Image.BILINEAR)
            img.alpha_composite(Q.with_alpha(fr, fa), (int(round(x - b)), int(round(y - b))))


# ---------------------------------------------------------------- 1問


def say_all(tts, lines):
    clips = {k: tts(t) for k, t in lines.items()}
    return clips, {k: len(v) / SR for k, v in clips.items()}


def round_art(art, img, no, total, tts, max_year):
    rng = random.Random(f"{art['source']}:{art['id']}")
    answer = Q.quiz_year(art)
    ys, correct = Q.make_choices(answer, rng, max_year)
    labels = Q.choice_labels(ys)
    say = [N.spoken_year(lb) for lb in labels]
    canvas = Canvas(img, rng)
    fact = timeline_facts.fact(art, answer)
    lines = {
        "q": f"Painting {no}. When was this painted?",
        "c": f"Was it {say[0]}, {say[1]}, or {say[2]}?",
        "ans": f"It's {say[correct]}!",
    }
    clips, dur = say_all(tts, lines)
    at = {"q": 0.3}
    pull = (0.2, max(2.6, at["q"] + dur["q"] + 0.4))
    at["c"] = at["q"] + dur["q"] + 0.3
    think = (at["c"] + dur["c"] + 0.2, at["c"] + dur["c"] + 0.2 + THINK)
    reveal = think[1] + 0.1
    at["ans"] = reveal + 0.15
    info_t = at["ans"] + 0.4
    end = max(MIN_CHAPTER, info_t + 4.2)                     # 題名・作者・年を読める時間
    effects = [(N.sfx_whoosh(), 0.05), (N.sfx_pop(), at["c"])]
    effects += [(N.sfx_tick(), think[0] + k) for k in range(int(THINK))]
    effects += [(N.sfx_ding(), reveal)]

    f_choice = font(46)
    q = text(["When was this", "painted?"], font(50), WHITE + (255,), spacing=1.08)
    pills = [Q.pill(lb, f_choice, (20, 20, 24, 220), WHITE, outline=(255, 255, 255, 120)) for lb in labels]
    right = Q.pill(labels[correct], f_choice, GOLD + (255,), (25, 20, 10))
    box = info_box(art, fact)
    credit = text([f"{art['museum']} · Public Domain (CC0)"], font(22, bold=False), (215, 210, 200, 230),
                  width=W - PANEL_W, shadow=200)

    def frame(t):
        img2 = canvas.bg.copy()
        canvas.draw(img2, A.ease((t - pull[0]) / (pull[1] - pull[0])))
        chrome(img2, no, total, credit)
        r = A.ease((t - reveal) / 0.3)
        qa = 1 - A.ease((t - info_t) / 0.4)
        if qa > 0:
            img2.alpha_composite(Q.with_alpha(q, qa), (0, 220))
        for k, p in enumerate(pills):
            a_in = A.ease((t - at["c"] - 0.3 * k) / 0.3)
            px, py = (PANEL_W - p.width) // 2, 360 + k * 108
            if info_t <= t:                                     # 答えのあとは、正解だけを上に残す
                if k == correct:
                    img2.alpha_composite(right, ((PANEL_W - right.width) // 2, 230))
                continue
            if k == correct and r > 0:
                img2.alpha_composite(Q.with_alpha(p, 1 - r), (px, py))
                img2.alpha_composite(Q.with_alpha(right, r), (px, py))
            elif a_in > 0:
                img2.alpha_composite(Q.with_alpha(p, a_in * (1 - 0.7 * r)), (px, py))
        countdown(img2, t, think[0], think[1], y=790)
        ia = A.ease((t - info_t) / 0.5)
        if ia > 0:
            img2.alpha_composite(Q.with_alpha(box, ia), (0, 360))
        return img2

    thumb = img.copy()
    thumb.thumbnail((360, 360))
    return dict(clips=clips, at=at, effects=effects, end=end, frame=frame, key=f"{art['source']}:{art['id']}",
                art=art, year=answer, thumb=thumb, thumb_t=(think[0] + think[1]) / 2,
                answer=f"{labels[correct]} — “{art['title']}” by {art['artist']} ({art.get('date') or ''}), "
                       f"{art['museum']}")


# ---------------------------------------------------------------- 導入と最後


def intro(tts, total, bg):
    lines = {"hi": f"Welcome to the Art History Timeline Challenge! {total} famous paintings, "
                   f"{int(THINK)} seconds each. Guess when each one was painted, and keep score!"}
    clips, dur = say_all(tts, lines)
    at = {"hi": 0.4}
    end = max(MIN_CHAPTER, at["hi"] + dur["hi"] + 0.8)
    t1 = text(["ART HISTORY", "TIMELINE", "CHALLENGE"], font(64), GOLD + (255,), spacing=1.05)
    t2 = text([f"{total} paintings · {int(THINK)} seconds each"], font(32, bold=False), WHITE + (255,))
    t3 = text(["Keep score!"], font(44), WHITE + (255,))

    def frame(t):
        img = bg.copy()
        chrome(img)
        img.alpha_composite(Q.with_alpha(t1, A.ease(t / 0.6)), (0, 280))
        img.alpha_composite(Q.with_alpha(t2, A.ease((t - 0.8) / 0.5)), (0, 560))
        img.alpha_composite(Q.with_alpha(t3, A.ease((t - 1.6) / 0.5)), (0, 660))
        return img
    return dict(clips=clips, at=at, effects=[(N.sfx_whoosh(), 0.1)], end=end, frame=frame)


def outro(tts, rounds, bg):
    """10点を制作年の順に年表に並べる。"""
    total = len(rounds)
    order = sorted(rounds, key=lambda r: r["year"])
    y0, y1 = order[0]["year"], order[-1]["year"]
    span = y1 - y0
    lines = {"how": f"Here they are in order, from {N.spoken_year(Q.year_label(y0))} to "
                    f"{N.spoken_year(Q.year_label(y1))}. That's {span} years of art history! "
                    "How many did you get right? Tell me your score in the comments!"}
    clips, dur = say_all(tts, lines)
    at = {"how": 0.4}
    end = max(MIN_CHAPTER, at["how"] + dur["how"] + 3.0)
    t1 = text(["How many did", "you get right?"], font(54), WHITE + (255,), spacing=1.1)
    hi, mid = math.ceil(total * 0.8), math.ceil(total * 0.5)
    tiers = text([f"{hi}–{total}: Art historian", f"{mid}–{hi - 1}: Gallery regular", f"0–{mid - 1}: Museum tourist"],
                 font(34), GOLD + (255,), spacing=1.5)
    # 年表(右の範囲)
    ax0, ax1, ay = PANEL_W + 90, W - 90, 640
    n = len(order)
    slots = [ax0 + (ax1 - ax0) * (k + 0.5) / n for k in range(n)]
    cw = min(150, (ax1 - ax0) / n - 14)
    cards = []
    for r in order:
        th = r["thumb"].copy()
        th.thumbnail((int(cw), 200))
        cards.append(th)
    f_year = font(26)
    f_span = font(40)

    def frame(t):
        img = bg.copy()
        d = ImageDraw.Draw(img)
        a_ax = A.ease(t / 0.6)
        d.line([ax0 - 30, ay, ax1 + 30, ay], fill=GOLD + (int(255 * a_ax),), width=4)
        for k, (r, x, c) in enumerate(zip(order, slots, cards)):
            a = A.ease((t - 0.4 - 0.25 * k) / 0.4)
            if a <= 0:
                continue
            yy = ay - 30 - c.height if k % 2 == 0 else ay + 30
            img.alpha_composite(Q.with_alpha(c.convert("RGBA"), a), (int(x - c.width / 2), int(yy)))
            d.ellipse([x - 8, ay - 8, x + 8, ay + 8], fill=GOLD + (int(255 * a),))
            ty = yy - 22 if k % 2 == 0 else yy + c.height + 22
            d.text((x, ty), Q.year_label(r["year"]), font=f_year, fill=WHITE + (int(255 * a),), anchor="mm",
                   stroke_width=3, stroke_fill=NAVY + (int(255 * a),))
        sa = A.ease((t - 0.6 - 0.25 * n) / 0.5)
        if sa > 0:
            d.text(((ax0 + ax1) / 2, 110), f"{span} years of art history", font=f_span, fill=GOLD + (int(255 * sa),),
                   anchor="mm", stroke_width=4, stroke_fill=NAVY + (255,))
        chrome(img)
        img.alpha_composite(Q.with_alpha(t1, A.ease(t / 0.5)), (0, 260))
        img.alpha_composite(Q.with_alpha(tiers, A.ease((t - 0.8) / 0.5)), (0, 460))
        return img
    return dict(clips=clips, at=at, effects=[(N.sfx_ding(), 0.2)], end=end, frame=frame)


# ---------------------------------------------------------------- 作品の選び方


def pick(n, shorts_history, long_history, rng, sources, log=print):
    """有名な画家(artists.py)の本人の作品で、Shorts と過去の通常動画で使っていないものを n 点。
    1人の画家は1点、1つの世紀は PER_CENTURY 点まで。美術館は交互に(失敗が続いたらもう一方だけで)。"""
    used = [{"source": h["source"], "id": h["id"]} for h in shorts_history if h.get("source")]
    used += [{"source": k.split(":")[0], "id": k.split(":", 1)[1]} for h in long_history for k in h.get("keys", [])]
    gens = {s: A._famous_candidates(A.SOURCES[s](), rng, used, Q.accept, ()) for s in sources}
    chosen, artists, cents = [], set(), {}
    order = list(sources)
    k = 0
    misses = 0
    while len(chosen) < n and order:
        s = order[k % len(order)]
        k += 1
        try:
            art = next(gens[s])
        except StopIteration:
            order.remove(s)
            continue
        except A.HTTPStatusError as e:
            log(f"  {s}: 美術館の API が失敗し続けたので、この回はもう一方だけを使います({e})")
            order.remove(s)
            continue
        name = art.get("famous_artist")
        c = Q.quiz_year(art) // 100
        if name in artists or cents.get(c, 0) >= PER_CENTURY:
            misses += 1
            if misses > 200:
                break
            continue
        try:
            img = A.download_image(art)
        except Exception as e:  # noqa: BLE001
            log(f"  {art['source']}:{art['id']} の画像を取れません({e})")
            continue
        chosen.append((art, img))
        artists.add(name)
        cents[c] = cents.get(c, 0) + 1
        log(f"  {len(chosen)}. {name} 「{art['title'][:40]}」 {art.get('date')}")
    if len(chosen) < n:
        raise SystemExit(f"作品が足りません({len(chosen)}/{n})")
    rng.shuffle(chosen)                 # 年代順にしない(最後の年表で順に並べる)
    return chosen


# ---------------------------------------------------------------- 組み立て


def mix(segments):
    total = sum(s["end"] for s in segments)
    n = int(math.ceil(total * SR)) + SR
    voice, fx = np.zeros(n, np.float32), np.zeros(n, np.float32)

    def put(buf, x, t):
        i = int(t * SR)
        x = x[: max(0, n - i)]
        buf[i:i + len(x)] += x
    t0 = 0.0
    for s in segments:
        for k, x in s["clips"].items():
            put(voice, x, t0 + s["at"][k])
        for x, t in s["effects"]:
            put(fx, x, t0 + t)
        t0 += s["end"]
    m = voice / max(1e-6, float(np.abs(voice).max())) * 0.8 + fx * 0.35
    m /= max(1.0, float(np.abs(m).max()) / 0.95)
    return m, total


def write_wav(path, m):
    pcm = (np.clip(np.stack([m, m], 1), -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def starts_of(segments):
    out, t0 = [], 0.0
    for s in segments:
        out.append(t0)
        t0 += s["end"]
    return out


def render(mp4, wav, segments, total):
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-i", str(wav), "-map", "0:v", "-map", "1:a", "-shortest",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(mp4)], stdin=subprocess.PIPE)
    starts = starts_of(segments)
    try:
        k = 0
        for f in range(int(round(total * FPS))):
            t = f / FPS
            while k + 1 < len(segments) and t >= starts[k + 1]:
                k += 1
            p.stdin.write(segments[k]["frame"](t - starts[k]).convert("RGB").tobytes())
            if f % (FPS * 30) == 0:
                print(f"  {t:.0f}/{total:.0f} 秒", flush=True)
    finally:
        p.stdin.close()
        if p.wait() != 0:
            raise RuntimeError("ffmpeg が失敗しました")


def stamp(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def check_chapters(starts, total):
    ends = starts[1:] + [total]
    short = [(stamp(a), round(b - a, 1)) for a, b in zip(starts, ends) if b - a < 10]
    if len(starts) < 3 or short:
        raise SystemExit(f"チャプターが YouTube の決まりを満たしません(10秒未満: {short})")


def thumbnail(seg, number, total, path, style="a"):
    """サムネイル(1280x720)。問題の途中のコマ(答えはまだ)に大きな文字を重ねる。
    a = 題名(投稿のときに設定)/ b = 「When was this painted?」/ c = 「Can you get 10/10?」"""
    img = seg["frame"](seg["thumb_t"]).convert("RGBA")
    ImageDraw.Draw(img).rectangle([0, 0, PANEL_W, H], fill=NAVY + (255,))
    if style == "b":
        img.alpha_composite(text(["When was", "this", "painted?"], font(96), WHITE + (255,), spacing=1.0, shadow=255),
                            (0, 170))
        img.alpha_composite(text([f"Timeline Challenge #{number}"], font(40), GOLD + (255,), shadow=255), (0, 760))
    elif style == "c":
        img.alpha_composite(text(["Can you get", f"{total}/{total}?"], font(96), GOLD + (255,), spacing=1.0, shadow=255),
                            (0, 220))
        img.alpha_composite(text(["Guess the year", "of each painting"], font(52), WHITE + (255,), spacing=1.08,
                                 shadow=255), (0, 600))
    else:
        img.alpha_composite(text(["ART HISTORY", "TIMELINE"], font(78), GOLD + (255,), spacing=1.0, shadow=255), (0, 150))
        img.alpha_composite(text([f"#{number} · {total} paintings"], font(50), WHITE + (255,), shadow=255), (0, 430))
        img.alpha_composite(text(["Can you date", "them all?"], font(64), WHITE + (255,), spacing=1.05, shadow=255),
                            (0, 640))
    img.convert("RGB").crop((0, 0, W - 96, H - 54)).resize((1280, 720), Image.LANCZOS).save(path, quality=90)


def description(number, rounds, starts):
    museums = sorted({r["art"]["museum"] for r in rounds})
    lines = [
        f"Art History Timeline Challenge #{number}: {len(rounds)} famous paintings. You get {int(THINK)} seconds to "
        "guess when each one was painted. Keep score and tell me how many you got right! 🎨",
        "",
        "Chapters:",
        f"{stamp(starts[0])} Intro",
    ]
    for i, st in enumerate(starts[1:-1], 1):
        lines.append(f"{stamp(st)} Painting {i}")
    lines.append(f"{stamp(starts[-1])} The timeline")
    lines += ["", "⬇️ Answers below (spoilers!) ⬇️", ".", ".", "."]
    lines += [f"{i}. {r['answer']}" for i, r in enumerate(rounds, 1)]
    lines += ["", f"Images: {', '.join(museums)}, Public Domain (CC0). This channel is not affiliated with the museums.",
              "", f"A new painting quiz every day: {CHANNEL}", f"Website: {SITE}/",
              "", "#arthistory #artquiz #painting"]
    return "\n".join(lines)


def build(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    hp = Path(args.history) if args.history else None
    long_history = json.loads(hp.read_text().strip() or "[]") if hp and hp.exists() else []
    shorts = json.loads(SHORTS_HISTORY.read_text()) if SHORTS_HISTORY.exists() else []
    number = max([h["number"] for h in long_history], default=0) + 1
    rng = random.Random(f"long:{number}:{args.seed or ''}")
    n = args.rounds or ROUNDS
    sources = ["met", "aic"] if args.source == "both" else [args.source]
    print(f"#{number}: 作品を選んでいます", flush=True)
    chosen = pick(n, shorts, long_history, rng, sources)
    tts = N.make_tts(args.tts)
    max_year = datetime.now(TZ).year
    rounds = [round_art(art, img, i, n, tts, max_year) for i, (art, img) in enumerate(chosen, 1)]
    bg = A.make_background(chosen[0][1], (W, H)).convert("RGBA")
    segments = [intro(tts, n, bg)] + rounds + [outro(tts, rounds, bg)]
    m, total = mix(segments)
    starts = starts_of(segments)
    check_chapters(starts, total)
    wav = out / "audio.wav"
    write_wav(wav, m)
    print(f"動画を書き出しています({total:.0f} 秒)", flush=True)
    render(out / "video.mp4", wav, segments, total)
    wav.unlink()
    thumb_seg = max(rounds, key=lambda r: r["art"].get("famous_artist") is not None)
    thumbnail(thumb_seg, number, n, out / "thumbnail.jpg")
    for style in ("b", "c"):
        thumbnail(thumb_seg, number, n, out / f"thumbnail_{style}.jpg", style)
    meta = {
        "number": number,
        "keys": [r["key"] for r in rounds],
        "date": datetime.now(TZ).date().isoformat(),
        "video": "video.mp4",
        "thumbnail": "thumbnail.jpg",
        "seconds": round(total, 1),
        "title": f"Art History Timeline Challenge #{number}: Guess When These {n} Famous Paintings Were Made 🎨"[:100],
        "description": A._yt_text(description(number, rounds, starts))[:4900],
        "tags": ["art quiz", "art history", "painting", "guess the year", "famous paintings", "museum", "quiz",
                 "art history timeline"],
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    print(f"完了: {out / 'video.mp4'}({total:.0f} 秒)")
    print(meta["description"])


# ---------------------------------------------------------------- 投稿


THUMB_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={}"
PUBLISH_WEEKDAY = 2             # 予約投稿の曜日(月曜が 0)。水曜
PUBLISH_TIME = (19, 13)            # 予約投稿の時刻(日本時間)


def scheduled_publish(now=None):
    """定期実行で作った回を公開する時刻(UTC の RFC3339)。GitHub の定期実行は数時間遅れることがあるので、
    早めに作って非公開で上げ、この時刻に YouTube が公開する(publishAt)。もう間に合わなければ None(すぐ公開する)。"""
    from datetime import timedelta
    now = now or datetime.now(TZ)
    if 1 <= (now.weekday() - PUBLISH_WEEKDAY) % 7 <= 2:      # 定期実行が日付をまたいで遅れた: 来週にせず、すぐ公開
        return None
    day = now.date() + timedelta(days=(PUBLISH_WEEKDAY - now.weekday()) % 7)
    target = datetime(day.year, day.month, day.day, *PUBLISH_TIME, tzinfo=TZ)
    if now > target - timedelta(minutes=10):
        return None
    return target.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upload(args):
    import youtube_upload as Y
    out = Path(args.dir)
    meta = json.loads((out / "meta.json").read_text())
    hist_path = Path(args.history)
    history = json.loads(hist_path.read_text().strip() or "[]") if hist_path.exists() else []
    if any(h["number"] == meta["number"] for h in history):
        raise SystemExit(f"投稿済みの回です: #{meta['number']}")
    token = Y.connect()
    publish_at = scheduled_publish() if args.schedule else None
    if args.schedule and not publish_at:
        print("予約の時刻を過ぎたので、すぐ公開します")
    res = Y.upload(token, out / meta["video"], meta, args.privacy, publish_at)
    vid = res["id"]
    privacy = "public" if publish_at else res.get("status", {}).get("privacyStatus", args.privacy)
    if publish_at:
        print(f"予約投稿: {publish_at} に公開")
    print(f"uploaded: https://youtu.be/{vid} ({privacy})")
    Y.set_output("video_id", vid)
    thumb = out / meta.get("thumbnail", "thumbnail.jpg")
    if thumb.exists():
        try:
            Y.request(THUMB_URL.format(vid), data=thumb.read_bytes(), method="POST",
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "image/jpeg"})
            print("thumbnail ok")
        except Exception as e:
            detail = e.read().decode(errors="replace")[:300] if hasattr(e, "read") else str(e)
            print(f"警告: サムネイルを設定できませんでした(YouTube Studio で設定してください): {detail}", file=sys.stderr)
    history.append({
        "number": meta["number"], "keys": meta["keys"], "date": meta["date"], "title": meta["title"],
        "seconds": meta["seconds"], "video_id": vid, "privacy": privacy, "publish_at": publish_at,
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    hist_path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n")
    import playlists
    playlists.add_after_upload(token, history[-1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", default=str(HISTORY))
    ap.add_argument("--tts", choices=["google", "dummy"], default="google")
    ap.add_argument("--rounds", type=int, help=f"問題の数(既定 {ROUNDS})")
    ap.add_argument("--source", choices=["both", "met", "aic"], default="both")
    ap.add_argument("--seed")
    ap.add_argument("--out", default="out_long")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--dir", default="out_long")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--schedule", action="store_true", help="予約投稿にする(定期実行。scheduled_publish の時刻に公開)")
    args = ap.parse_args()
    if args.upload:
        upload(args)
    else:
        build(args)


if __name__ == "__main__":
    main()

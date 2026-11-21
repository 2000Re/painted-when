"""クイズのナレーション(英語)と効果音。声の長さから、画面の各場面の時刻(quiz.Timeline)を決める。

台本は作品データだけから作る(解説文の生成はしない):
  q      When was this painted?
  c0..2  Was it 1949? / 1889? / Or 1685?        … 読み上げに合わせて選択肢が1つずつ出る
  lock   Lock in your answer!                    … ここから残り時間のバー
  ans    It's 1889!                              … 正解が光る
  info   Wheat Field with Cypresses, by Vincent van Gogh.
  outro  How did you do? Tell me in the comments.

音声合成:
  google … Google Cloud Text-to-Speech。API キーは環境変数 GOOGLE_TTS_API_KEY(GitHub Actions など)か、
           Claude Code のクラウド環境の「Network secrets」(texttospeech.googleapis.com への通信に
           X-Goog-Api-Key ヘッダーを自動で付ける。この場合キーはプログラムからは見えない)で渡す。
           声は ART_SHORTS_TTS_VOICE(既定 en-US-Chirp3-HD-Charon)で変えられる
  dummy  … 通信なし。文の長さから見積もった長さの仮の音(タイミング確認用)
"""
import base64
import io
import json
import math
import os
import urllib.error
import urllib.request
import wave

import numpy as np

import art_shorts as A
import quiz

SR = 48000
DEFAULT_VOICE = "en-US-Chirp3-HD-Charon"
DEFAULT_RATE = 1.1          # 少し速めに読ませる(Shorts のテンポ)
LONG_TITLE = 60             # これより長い題名は読み上げない(画面には出る)
TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"


# ---------------------------------------------------------------- 台本


TAIL = 0.4          # 最後の読み上げのあとの間(秒)。以前は 1.0(2026-11-21 に短くした)
LOOP_SEC = 1.1      # 最後のこの秒数で、冒頭の拡大した場面に戻る(quiz.Timeline.loop)
READ_SEC = 2.2      # 答えのあと、作品名・作者・出来事との比較を読める時間(読み上げはしないので)

def spoken_year(label):
    """画面の表記を読み上げ用に。"50 BC" → "50 B.C."、"AD 224" → "A.D. 224"。"""
    if label.endswith(" BC"):
        return label[:-3] + " B.C."
    if label.startswith("AD "):
        return "A.D. " + label[3:]
    return label


# 毎回ちがう言い回し(繰り返しの多い動画に見えないように)。番号で回すので、同じ番号なら作り直しても同じ
LINES = {
    "q": ["When was this painted?", "Can you guess when this was painted?", "What year was this painted?",
          "Guess the year this was painted!", "When do you think this was painted?"],
    "lock": ["Lock in your answer!", "Pick your year!", "Got your guess?", "Make your choice!", "Final answer?"],
    "outro": ["How did you do? Tell me in the comments.", "Did you get the year right?",
              "Were you close? Let me know below!", "How many years off were you?",
              "Did you guess it? Comment your answer!"],
    "age": ["{name} painted this at around age {age}.", "{name} was about {age} when this was painted.",
            "This was painted when {name} was about {age}."],
}


def vary(number, key, **kw):
    opts = LINES[key]
    return opts[(number + sum(map(ord, key))) % len(opts)].format(**kw)


def age_fact(art, number=1):
    """「画家が何歳ごろに描いたか」の一文(美術館のデータの生没年と制作年から)。分からなければ None。"""
    import re
    m = re.search(r"(1[2-9]\d\d)\s*[–-]\s*(1[2-9]\d\d|20\d\d)", art.get("artist_bio") or "")
    year = art.get("year_start")
    name = art.get("artist") or ""          # 生没年(artist_bio)はこの作者のもの(famous_artist ではなく)
    if not m or not year or not name or name.lower() in ("unknown artist", "unidentified artist", "anonymous"):
        return None
    born, died = int(m.group(1)), int(m.group(2))
    age = year - born
    if not 14 <= age <= 95 or year > died + 1:
        return None
    return vary(number, "age", name=name, age=age)


def script(art, labels, correct, hook=False):
    number = art.get("number") or 1
    artist = art.get("artist") or ""
    if artist.lower() in ("", "unknown artist", "unidentified artist", "anonymous"):
        by = "by an unknown artist"
    else:
        by = f"by {artist}"
    ys = [spoken_year(lb) for lb in labels]
    return {
        "q": "Quick, guess the year!" if hook else vary(number, "q"),
        "c0": f"Was it {ys[0]}?",
        "c1": f"{ys[1]}?",
        "c2": f"Or {ys[2]}?",
        "lock": vary(number, "lock"),
        "ans": f"It's {ys[correct]}!",
        # 作品名・作者・年代の話は読み上げず、画面に出すだけ(2026-11-21〜。答えのあとに離れる人が多かったので短くした。
        # 以前は「<作品名>, by <作者>. <何歳ごろ>」を読んでいた。age_fact は説明欄で使う)
        "outro": vary(number, "outro"),
    }


# ---------------------------------------------------------------- 音声合成


def read_wav(raw):
    if raw[:4] != b"RIFF":    # ヘッダーなしの 16bit モノラル PCM(要求した SR)
        return np.frombuffer(raw[: len(raw) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768
    with wave.open(io.BytesIO(raw)) as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        t = np.arange(int(len(x) * SR / sr)) / SR
        x = np.interp(t, np.arange(len(x)) / sr, x).astype(np.float32)
    return x


def trim(x, thresh=0.01):
    """前後の無音を削る(場面の時刻を声に合わせるため)。"""
    idx = np.nonzero(np.abs(x) > thresh)[0]
    if len(idx) == 0:
        return x
    a, b = max(0, idx[0] - int(0.02 * SR)), min(len(x), idx[-1] + int(0.06 * SR))
    return x[a:b]


class GoogleTTS:
    name = "google"

    def __init__(self, api_key=None, voice=None, rate=None):
        # キーがなければヘッダーを付けずに送る(途中の proxy がキーを付ける環境のため)
        self.key = api_key or os.environ.get("GOOGLE_TTS_API_KEY")
        self.voice = voice or os.environ.get("ART_SHORTS_TTS_VOICE") or DEFAULT_VOICE
        self.rate = rate or float(os.environ.get("ART_SHORTS_TTS_RATE") or DEFAULT_RATE)

    def __call__(self, text):
        body = {
            "input": {"text": text},
            "voice": {"languageCode": "-".join(self.voice.split("-")[:2]), "name": self.voice},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SR, "speakingRate": self.rate},
        }
        # キーは URL ではなくヘッダーで渡す(ログに残りにくい)
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["X-Goog-Api-Key"] = self.key
        req = urllib.request.Request(TTS_URL, data=json.dumps(body).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            hint = "" if self.key else "(GOOGLE_TTS_API_KEY がなく、キーを付けずに送りました)"
            raise RuntimeError(f"Text-to-Speech が {e.code} を返しました{hint}: {detail}") from None
        return trim(read_wav(base64.b64decode(data["audioContent"])))


class DummyTTS:
    """通信なしの仮の声。1語あたり約0.32秒の、音節ごとに区切れた柔らかい音。"""
    name = "dummy"

    def __call__(self, text):
        words = text.replace("?", " ").replace("!", " ").replace(",", " ").split()
        syll = sum(max(1, len(w) // 3) for w in words)
        dur = 0.15 + 0.32 * len(words) + 0.03 * syll
        n = int(dur * SR)
        t = np.arange(n) / SR
        env = 0.5 - 0.5 * np.cos(2 * np.pi * np.clip(t * syll / dur, 0, None))
        f0 = 170 + 25 * np.sin(2 * np.pi * 0.8 * t)
        x = (np.sin(2 * np.pi * np.cumsum(f0) / SR) * env * 0.25).astype(np.float32)
        fade = np.minimum(1, np.minimum(t / 0.02, (dur - t) / 0.05))
        return x * fade


def make_tts(name):
    return {"google": GoogleTTS, "dummy": DummyTTS}[name]()


# ---------------------------------------------------------------- 効果音


def _env(n, attack, decay):
    t = np.arange(n) / SR
    return np.minimum(1, t / attack) * np.exp(-t / decay)


def sfx_pop():
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    f = 900 * np.exp(-t * 18) + 500
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 0.03) * 0.5).astype(np.float32)


def sfx_tick():
    n = int(0.05 * SR)
    noise = np.random.default_rng(0).standard_normal(n)
    noise = np.convolve(noise, [1, -1], mode="same")      # 高い音だけ残す
    return (noise * _env(n, 0.0005, 0.006) * 0.25).astype(np.float32)


def sfx_ding():
    n = int(1.4 * SR)
    t = np.arange(n) / SR
    x = sum(a * np.sin(2 * np.pi * f * t) * np.exp(-t / d)
            for f, a, d in [(1046.5, 0.5, 0.6), (1568.0, 0.3, 0.45), (2093.0, 0.15, 0.3), (2637.0, 0.08, 0.2)])
    return (x * np.minimum(1, t / 0.003) * 0.6).astype(np.float32)


# ---------------------------------------------------------------- 組み立て


def sfx_whoosh():
    """冒頭の「シュッ」。高い方へ抜けるノイズ。"""
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    noise = np.random.default_rng(1).standard_normal(n)
    # 時間とともに明るくなるよう、なめらかにする幅を狭めていく
    out = np.empty(n)
    acc, alpha0 = 0.0, 0.02
    for i in range(n):
        a = alpha0 + 0.5 * (t[i] / t[-1]) ** 2
        acc += a * (noise[i] - acc)
        out[i] = noise[i] - acc
    env = np.sin(np.pi * np.clip(t / 0.35, 0, 1)) ** 1.5
    return (out * env * 0.35).astype(np.float32)


def build(art, q, tts, hook=False):
    """声を合成して並べ、quiz.Timeline と、ミックスした音声(48kHz ステレオ float32)を返す。
    hook=True はフック版: 0秒に効果音、第一声は短く、選択肢と残り時間のバーは最初から出す。"""
    lines = script(art, q.labels, q.correct, hook)
    clips = {k: tts(text) for k, text in lines.items()}
    dur = {k: len(v) / SR for k, v in clips.items()}
    at = {}

    # 間は短めに(2026-11-21 に詰めた。平均視聴割合が Wait, That Big? の 90% 台に対して 50〜70% 台だったため)
    at["q"] = 0.08 if hook else 0.15
    q_end = at["q"] + dur["q"]
    pull = (0.4, max(2.4, q_end + 0.6))
    at["c0"] = max(pull[1] - 0.3, q_end + 0.25)
    at["c1"] = at["c0"] + dur["c0"] + 0.2
    at["c2"] = at["c1"] + dur["c1"] + 0.2
    at["lock"] = at["c2"] + dur["c2"] + 0.2
    timer = (at["lock"], at["lock"] + dur["lock"] + 1.5)
    reveal = timer[1] + 0.1
    at["ans"] = reveal + 0.15
    # 答えを言い始めたら、作品名・作者・年と技法・出来事との比較を続けて出す(読み上げはしない)
    a0 = at["ans"] + 0.3
    info = (a0, a0 + 0.1, a0 + 0.2, a0 + 0.3)
    at["outro"] = at["ans"] + dur["ans"] + 0.35
    # 作品名などを読める時間(出そろってから、冒頭へ戻り始めるまで)を READ_SEC 以上とる
    end = max(at["outro"] + dur["outro"] + TAIL, info[-1] + 0.6 + READ_SEC + LOOP_SEC)
    loop = (end - LOOP_SEC, end)

    if hook:
        timer = (0.0, timer[1])     # 残り時間のバーは最初のコマから、答えの直前まで
    tl = quiz.Timeline(pull=pull, choices=tuple(at[f"c{i}"] for i in range(3)), timer=timer,
                       reveal=reveal, info=info, outro=at["outro"], end=end, hook=hook, loop=loop)

    n = int(math.ceil(end * SR))
    voice = np.zeros(n, np.float32)
    fx = np.zeros(n, np.float32)

    def put(buf, x, t):
        i = int(t * SR)
        x = x[: max(0, n - i)]
        buf[i:i + len(x)] += x

    for k, x in clips.items():
        put(voice, x, at[k])
    for i in range(3):
        put(fx, sfx_pop(), at[f"c{i}"])
    tick = sfx_tick()
    t = max(timer[0], timer[1] - 3.0) if hook else timer[0]    # フック版は最後の3秒だけ鳴らす
    if hook:
        put(fx, sfx_whoosh(), 0.0)
    while t < timer[1] - 0.05:
        put(fx, tick, t)
        t += 0.5
    put(fx, sfx_ding(), reveal)

    peak = max(1e-6, float(np.abs(voice).max()))
    mix = voice / peak * 0.8 + fx * 0.35
    mix /= max(1.0, float(np.abs(mix).max()) / 0.95)
    stereo = np.stack([mix, mix], axis=1)
    return tl, stereo, lines, at


def write_wav(path, stereo):
    pcm = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())

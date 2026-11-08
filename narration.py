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


def spoken_year(label):
    """画面の表記を読み上げ用に。"50 BC" → "50 B.C."、"AD 224" → "A.D. 224"。"""
    if label.endswith(" BC"):
        return label[:-3] + " B.C."
    if label.startswith("AD "):
        return "A.D. " + label[3:]
    return label


def script(art, labels, correct, hook=False):
    artist = art.get("artist") or ""
    if artist.lower() in ("", "unknown artist", "unidentified artist", "anonymous"):
        by = "by an unknown artist"
    else:
        by = f"by {artist}"
    ys = [spoken_year(lb) for lb in labels]
    return {
        "q": "Quick, guess the year!" if hook else "When was this painted?",
        "c0": f"Was it {ys[0]}?",
        "c1": f"{ys[1]}?",
        "c2": f"Or {ys[2]}?",
        "lock": "Lock in your answer!",
        "ans": f"It's {ys[correct]}!",
        "info": (f"{art['title'].rstrip('.')}, {by}." if len(art["title"]) <= LONG_TITLE
                 else f"{by[0].upper()}{by[1:]}."),
        "outro": "How did you do? Tell me in the comments.",
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

    at["q"] = 0.08 if hook else 0.15
    q_end = at["q"] + dur["q"]
    pull = (0.5, max(3.0, q_end + 1.0))
    at["c0"] = max(pull[1] - 0.3, q_end + 0.4)
    at["c1"] = at["c0"] + dur["c0"] + 0.3
    at["c2"] = at["c1"] + dur["c1"] + 0.3
    at["lock"] = at["c2"] + dur["c2"] + 0.35
    timer = (at["lock"], at["lock"] + dur["lock"] + 2.0)
    reveal = timer[1] + 0.1
    at["ans"] = reveal + 0.15
    at["info"] = at["ans"] + dur["ans"] + 0.4
    # 題名を読み始めたら題名、"by" のあたりで作者、読み終わりで年と技法を出す
    if ", by " in lines["info"]:
        title_chars = len(lines["info"].split(", by ")[0])
        by_t = at["info"] + dur["info"] * title_chars / max(1, len(lines["info"]))
    else:                       # 題名を読まないときは、題名と作者を続けて出す
        by_t = at["info"] + 0.4
    info = (at["info"], by_t, at["info"] + dur["info"])
    at["outro"] = at["info"] + dur["info"] + 0.7
    end = at["outro"] + dur["outro"] + 1.0

    if hook:
        timer = (0.0, timer[1])     # 残り時間のバーは最初のコマから、答えの直前まで
    tl = quiz.Timeline(pull=pull, choices=tuple(at[f"c{i}"] for i in range(3)), timer=timer,
                       reveal=reveal, info=info, outro=at["outro"], end=end, hook=hook)

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

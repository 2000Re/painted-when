# Painted When? — 名画の「いつ描かれた？」クイズ

YouTube チャンネル [@painted-when](https://www.youtube.com/@painted-when) の動画を作る。
美術館のオープンデータから、パブリックドメインの絵画を1日1点選び、「When was this painted?」の3択クイズの縦型動画にする。

## チャンネルの素材(`branding/`)

| ファイル | 内容 |
|---|---|
| `icon.png` | アイコン 800x800(ゴッホ「Wheat Field with Cypresses」の空に「?」) |
| `banner.png` | バナー 2560x1440(文字は中央 1546x423 に収めている) |
| `description.txt` | チャンネルの説明(英語) |

`python tools/make_branding.py` で作り直せる(美術館の API から絵を取得するので通信が必要)。

## 必要なもの

- Python 3.10以上、`pip install -r requirements.txt`(Pillow・numpy)
- ffmpeg(ffprobe も使う)
- フォントは `fonts/` に同梱(Liberation Serif / Sans、SIL OFL 1.1)

## 使い方

```sh
python art_shorts.py --demo                      # 仮画像でレイアウト確認(通信なし)。--demo-index 0〜3 で縦長・横長などを切り替え
python art_shorts.py                             # Met から今日の1点(縦型 1080x1920、3択クイズ)
python art_shorts.py --style classic             # 縦型で、クイズなしの作品紹介
python art_shorts.py --source aic --format wide  # シカゴ美術館から、横型 1920x1080
python art_shorts.py --audio narration.mp3       # 動画の長さ = 音声 + 1秒(末尾は無音)
python art_shorts.py --id 436535                 # 作品を指定(used.json に記録しない)
python art_shorts.py --still                     # 動画を作らず、サムネだけ(見栄え確認用)
```

出力(`out/`):

| ファイル | 内容 |
|---|---|
| `{日付}_{source}_{id}_quiz.mp4` | クイズの動画(縦型の既定)。読み上げありで17〜19秒、なしで13秒 |
| `..._quiz_voice.wav` | クイズの読み上げと効果音 |
| `{日付}_{source}_{id}.mp4` | 作品紹介の動画(`--style classic`。横型は `_wide.mp4`)。15秒 |
| `{日付}_{source}_{id}.jpg` | 作品画像(長辺2400pxまで) |
| `{日付}_{source}_{id}.json` | 作品情報(題名・作者・年・技法・URL・出典、クイズの選択肢と正解) |
| `{日付}_{source}_{id}.txt` | 台本(英語)。クイズで読み上げたときは、読み上げた文 |
| `..._thumb.png` | サムネ(クイズは選択肢が出て答えはまだの状態、作品紹介は全部の文字が出た状態) |
| `used.json` | 使用済みの作品。同じ作品は二度選ばない |

## 作品の選び方

- 日付(日本時間)+ source をシードにするので、同じ日は同じ作品になる。その日すでに `used.json` に記録があれば、その作品を使う
- **Met**: `v1.1/search?q=painting&isHighlight=true&hasImages=true&limit=500` で候補を取り、ランダムな順に
  `v1/objects/{id}` を見て、`isPublicDomain` が true・`primaryImage` あり・分類が絵画のものを選ぶ(最大60件まで調べる)
- **AIC**: `artworks/search?q=painting&limit=100` の1ページ目でページ数を知り、ランダムなページから、
  `is_public_domain` が true・`image_id` あり・`artwork_type_title` が Painting のものを選ぶ。
  画像は `{config.iiif_url}/{image_id}/full/843,/0/default.jpg`
- パブリックドメイン(CC0)以外の画像は使わない。AIC の `description`(CC-BY)は取得しない
- レート制限: Met は1秒5回まで、AIC は1.1秒に1回まで。429・5xx は待って再試行する
- `User-Agent` / `AIC-User-Agent` は環境変数 `ART_SHORTS_USER_AGENT` で変えられる(連絡先を入れておくとよい)

## クイズ(縦型の既定、`quiz.py`)

「When was this painted?」の3択。全部データから自動で作るので、解説文はいらない。

| 秒 | 画面 |
|---|---|
| 0〜0.5 | 絵の一部を画面いっぱいに映す(最初のコマから問いを表示)。場所は、細かい模様の多いところを自動で選ぶ |
| 0.5〜3.2 | 引いていき、額縁に収まった全体を見せる |
| 3.0〜 | 3択が順に出る。4.0〜8.0 は残り時間のバーが減る |
| 8.2 | 正解が金色に光る |
| 8.8〜13 | 題名・作者・美術館の年の表記・技法 |

- 制作年の幅(Met `objectBeginDate`〜`objectEndDate`、AIC `date_start`〜`date_end`)が10年以内の作品だけ使う。
  「14世紀前半」のような作品は選ばない(`--style classic` なら使える)
- 正解は開始の年。外れは正解から45〜220年(1500年より前はもっと広く)離し、外れ同士も離す。
  未来の年や0年にはしない。紀元前が混ざるときは紀元後に `AD` を付ける
- 選択肢は作品ごとに固定(同じ作品なら何度作っても同じ)
- 冒頭の拡大のため、画像は長辺4000pxまで残す。AIC は 1686px 幅を取り、だめなら 843px 幅にする
- 最初と最後はフェードしない(Shorts はループ再生される)

## 読み上げ(`narration.py`)

クイズは英語で読み上げる。台本は作品データだけから作り、声の長さに合わせて画面の場面の時刻を決める
(選択肢は読み上げに合わせて1つずつ出て、「It's 1889!」と同時に正解が光る)。長さは17〜19秒ほど
(2026-11-05、`en-US-Neural2-J`・1.1倍速で確認)。60文字を超える題名は読まず、作者だけ読む(題名は画面に出る)。

```
When was this painted?
Was it 1949? / 1889? / Or 1685?
Lock in your answer!            ← ここから残り時間のバー(コチコチ音)
It's 1889!                      ← 正解が光る(チャイム)
Wheat Field with Cypresses, by Vincent van Gogh.
How did you do? Tell me in the comments.   ← 上の問いが「How did you do?」に変わる
```

```sh
GOOGLE_TTS_API_KEY=... python art_shorts.py     # Google Cloud Text-to-Speech で読み上げ(キーがあれば既定)
python art_shorts.py --tts dummy               # 通信なしの仮の音で、タイミングだけ確認
python art_shorts.py --tts none                # 読み上げなし(13秒・無音)
```

- 声は `ART_SHORTS_TTS_VOICE`(既定 `en-US-Neural2-J`)、速さは `ART_SHORTS_TTS_RATE`(既定 1.1)で変えられる。
  `en-US-Neural2-J/D/F`、`en-US-Studio-Q/O`、`en-US-Chirp3-HD-Charon/Aoede`、`en-GB-Neural2-B/C` は使えることを確認済み
- キーは `X-Goog-Api-Key` ヘッダーで送る(URL に載せない)。Claude Code のクラウド環境では、環境変数ではなく
  「Network secrets」に登録する(許可ウェブサイト `texttospeech.googleapis.com`、ヘッダー名 `X-Goog-Api-Key`、
  プレフィックスは空欄)。この場合は `--tts google` を明示して実行する。キーは Google Cloud のコンソールで作り、
  使える API を Cloud Text-to-Speech API だけに制限しておく。GitHub Actions では Secret に入れる
- 合成した音声は `..._quiz_voice.wav`、台本と各行の開始時刻は作品情報 json の `quiz.narration` に残る
- 効果音(選択肢のポン、残り時間のコチコチ、正解のチャイム)は numpy で合成している

## 作品紹介(`--style classic`、横型の既定)

- ぼかした作品を背景にし、額縁風の枠に作品を置いて、15秒かけて7%ほどゆっくりズームする
- 題名(斜体)→ 作者 → 年・技法 の順に、1秒ずつずらしてフェードイン。出典は最初から表示
- 題名は3行に収まる最大の字の大きさにし、収まらなければ … で切る。技法は2行まで
- Shorts は画面下部の約430pxと右端の約150pxにYouTubeの表示が重なるので、文字はその外に置く

## APIの確認状況

このコードは、美術館のAPIに通信できない環境で書き、あとから実際のAPIで確かめた。

2026-11-05 に実際のAPIで確認済み:
- Met `v1.1/search` は v1 と同じ `{"total", "objectIDs": [...]}` の形。`limit=500` で500件返る(ハイライトの絵画は全864件)
- AIC のフィールド名 `artist_display` / `artist_title` / `date_display` / `medium_display` / `artwork_type_title` は存在する。
  `artist_display` は `Georges Seurat (French, 1859–1891)` の1行形式なので、作者名は `artist_title` を使う
- 作品選び・画像のダウンロード(`images.metmuseum.org`、`www.artic.edu/iiif`)・動画の書き出しは Met・AIC とも通る
- 同じ日に再実行すると、`used.json` の記録から同じ作品を選び直す
- 年のフィールド Met `objectBeginDate` / `objectEndDate`、AIC `date_start` / `date_end` は数値で入っている
  (例: 「ca. 50–40 BCE」は -50 / -40)。AIC の画像は 1686px 幅も取れる(`max` は 403)
- 実物の作品(掛軸のような縦長、フレスコ、点描の横長、長い題名)で、縦型・横型とも文字がはみ出さないことを確認した

気づいた点:
- Met のハイライトには、絵画以外の分類でも `objectName` が Wall painting のフレスコや、作者不明(`Unidentified artist`)の作品が入る
- Met の画像には、撮影時の黒い余白が入っているものがある(例: ゴッホ「Wheat Field with Cypresses」)
- Shorts で横長の作品は小さくなる。額縁の右端は、YouTube の右側のボタンと少し重なることがある

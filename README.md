# Painted When? — 名画の「いつ描かれた？」クイズ

YouTube チャンネル [@painted-when](https://www.youtube.com/@painted-when) の動画を作る。
美術館のオープンデータから、パブリックドメインの絵画を1日1点選び、「When was this painted?」の3択クイズの縦型動画にする。

## 自動投稿(GitHub Actions)

`.github/workflows/post.yml` が1日3本、@painted-when に投稿する。
cron-job.org から `workflow_dispatch`(`scheduled=true`)で、毎日 07:17・10:17・22:17 JST に起動する
(米国東部の夕方・夜・朝)。GitHub 自身の定期実行(schedule)は、数時間遅れるのが常で時刻が読めない
(2026-11-06 は 09:17 の予定が 15:52 に動いた)ので使わない。

1. **check**: cron-job.org からの起動は、リポジトリ変数 `AUTO_POST` が `true` のときだけ動き、今日(日本時間)
   すでに3本投稿済みか、最後の投稿から1.5時間たっていなければ止まる(`posted_today.py`)。
   手動の Run workflow はいつでも動き、このチェックもしない
2. **generate**: `art_shorts.py --source auto --history upload_history.json --tts google` で動画と `out/meta.json`
   (タイトル・説明文・タグ)を作る。美術館は Met とシカゴ美術館を1日ごとに交互にし、投稿済みの作品は選ばない
3. **upload**: `youtube_upload.py` でアップロード(カテゴリは Education、言語は英語)し、`upload_history.json` に記録してコミットする
4. 失敗したら Issue を立てる(トークン失効は `token-invalid`、それ以外は `post-failure` ラベル)

タイトルは「When was this painted? 🎨 Daily Art Quiz #連番」。答えはタイトルに書かず、説明文の下の方に、
作品名・作者・美術館のページへのリンク・出典(CC0)と一緒に書く。

### 使っている Google Cloud プロジェクト

**Painted When? 専用の Google アカウント**の、プロジェクト **`painted-when`** にまとめてある
(ねこピアノ・Can You Say This? とは別のアカウント・別のプロジェクト)。

| 中身 | 用途 | GitHub Secrets |
|---|---|---|
| API キー `painted-when`(Cloud Text-to-Speech API だけに制限) | 読み上げ | `GOOGLE_TTS_API_KEY` |
| OAuth クライアント(デスクトップアプリ)・OAuth 同意画面「Painted When? Uploader」(本番環境) | YouTube への投稿 | `YT_CLIENT_ID` など |
| YouTube Data API v3・Cloud Text-to-Speech API の有効化 | | |

**このプロジェクトを削除すると、読み上げと投稿の両方が止まる。** 別のアカウントのプロジェクトを整理するときに間違えないこと。

### セットアップ

0. **ホームページとプライバシーポリシー**: `docs/` を GitHub Pages で公開する
   (Settings → Pages → Source「Deploy from a branch」→ Branch `main`、フォルダ `/docs`)。
   公開先は https://2000re.github.io/painted-when/ (ホーム)、`privacy.html`(プライバシーポリシー)、`terms.html`(利用規約)
1. **Google Cloud**(Text-to-Speech の API キーを作ったプロジェクト `painted-when` で):
   1. 「API とサービス」→「ライブラリ」で **YouTube Data API v3** を有効にする
   2. 「OAuth 同意画面」(Google Auth Platform)を作る
      - アプリ名 `Painted When? Uploader`、ユーザーサポートメール・デベロッパーの連絡先は自分のメール
      - 対象(User type)は「外部」
      - アプリのホームページ `https://2000re.github.io/painted-when/`、
        プライバシーポリシー `https://2000re.github.io/painted-when/privacy.html`、
        利用規約 `https://2000re.github.io/painted-when/terms.html`
      - 承認済みドメイン `2000re.github.io`
      - スコープ(データアクセス)に `.../auth/youtube.upload` と `.../auth/youtube.readonly` を追加
      - ロゴは設定しない(設定すると Google の確認が必要になる)
   3. 公開ステータスを「本番環境」にする(「テスト」のままだとリフレッシュトークンが7日で切れる)。
      確認(verification)は申請しなくてよい。自分しか使わないので、ログイン時の「確認されていません」の警告を進めばよい
   4. 「認証情報」→「OAuth クライアント ID を作成」→ 種類「デスクトップアプリ」。JSON をダウンロードする
2. **リフレッシュトークン**(ローカル PC で一度だけ):
   ```sh
   pip install google-auth-oauthlib
   python3 get_youtube_refresh_token.py client_secret_xxx.json
   ```
   ブラウザのアカウント選択で **Painted When?(@painted-when)のチャンネルを選ぶ**。表示されたチャンネル名を必ず確認する
3. **GitHub**: Settings → Secrets and variables → Actions に登録する

   | 種類 | 名前 | 値 |
   |---|---|---|
   | Secret | `YT_CLIENT_ID` | 手順2の出力 |
   | Secret | `YT_CLIENT_SECRET` | 手順2の出力 |
   | Secret | `YT_REFRESH_TOKEN` | 手順2の出力 |
   | Secret | `YT_CHANNEL_ID` | 手順2の出力。別チャンネルへの誤投稿を防ぐ |
   | Secret | `GOOGLE_TTS_API_KEY` | Text-to-Speech の API キー |
   | Variable | `AUTO_POST` | `true` で定期投稿を有効にする。手順4のテスト投稿が成功してから設定する |

4. **動作確認**: Actions → post → Run workflow で、まず `dry_run` にチェックを入れて実行し、artifact の動画を確認する。
   次に `privacy: private` で1本投稿してみる。問題なければ変数 `AUTO_POST` を `true` にする

5. **cron-job.org**(毎日の本命の起動)
   1. GitHub で fine-grained personal access token を作る(Settings → Developer settings → Personal access tokens →
      Fine-grained tokens)。Repository access は `2000Re/painted-when` だけ、Permissions は **Actions: Read and write** だけ。
      有効期限が切れたら作り直して、cron-job.org のヘッダーを差し替える
   2. cron-job.org でジョブを作る

      | 項目 | 値 |
      |---|---|
      | URL | `https://api.github.com/repos/2000Re/painted-when/actions/workflows/post.yml/dispatches` |
      | 実行スケジュール | 毎日 07:17・10:17・22:17、タイムゾーン Asia/Tokyo(時刻ごとにジョブを分けてもよい) |
      | Request method | `POST` |
      | Headers | `Accept: application/vnd.github+json`<br>`Authorization: Bearer <トークン>`<br>`X-GitHub-Api-Version: 2022-11-28`<br>`Content-Type: application/json` |
      | Request body | `{"ref":"main","inputs":{"scheduled":"true"}}` |

      成功すると HTTP 204 が返る。`X-GitHub-Api-Version: 2022-11-28` は **2028-03-10 に提供終了**なので、それまでに書き換えること

### 注意

- **新しい API プロジェクトからアップロードした動画は、YouTube の監査(audit)を通るまで非公開に固定される。**
  公開で投稿するには「YouTube API Services - Audit and Quota Extension Form」で監査を申請する
  (審査ではホームページ・プライバシーポリシー・利用規約と、アプリの使い方を聞かれる)。
  `public` を指定したのに非公開になったら、`youtube_upload.py` が警告を出し、履歴の `privacy` にも実際の公開設定が残る
- YouTube Data API の割り当て(1日あたり)はプロジェクト単位。新しいプロジェクトなので、ねこピアノとは共有しない
- 定期実行は cron-job.org だけなので、`post.yml` を変更しても GitHub の画面でコミットし直す必要はない

## 冒頭の版の比較(2026-11-08〜)

冒頭を2つの版で作り、2本ずつ交互に投稿して反応を比べている(`--variant auto`)。

| 版 | 冒頭 |
|---|---|
| `base`(今の版) | 拡大した絵と問いから始まり、選択肢は3秒あたりから順に出る。声は0.15秒から「When was this painted?」 |
| `hook`(フック版) | 最初のコマから3択と残り時間のバーを出す(読み上げに合わせて選択肢が弾む)。0秒に効果音、声は「Quick, guess the year!」 |

美術館は1本ごとに交互なので、版と美術館の組み合わせは4通りとも均等に出る。どの動画がどちらの版かは
`python tools/variants.py` で一覧にできる(`upload_history.json` の `variant`)。1〜2週間たったら、YouTube Studio の
「スワイプされずに視聴された割合」と「平均視聴率」を版ごとに比べ、良い方に揃える。

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

- **有名な画家だけ**(`artists.py` の約90人)。毎回、画家をランダムに選び(直近10本の画家は後回し)、その画家の
  本人の作品から未使用のものを選ぶ。「工房」「追随者」「〜風」「〜の模写」などは使わない(Met の `artistPrefix`、
  作者名の書き方で判定)。2026-11 の集計では、クイズに使える作品は64人で約740点(1日3本で約8か月分)
- **Met**: `v1.1/search?q=画家名&artistOrCulture=true&hasImages=true&limit=500` で候補を取り、ランダムな順に
  `v1/objects/{id}` を見て、`isPublicDomain` が true・`primaryImage` あり・分類が絵画のものを選ぶ(1人あたり最大30件)。
  旧 `v1/search` は廃止済み(410)
- **AIC**: `artworks/search?q=画家名&limit=100`(最大3ページ)から、`is_public_domain` が true・`image_id` あり・
  `artwork_type_title` が Painting のものを選ぶ。画像は `{config.iiif_url}/{image_id}/full/1686,/0/default.jpg`
- `--any-artist` を付けると、以前の選び方(Met はハイライト、AIC は検索結果のランダムなページ)に戻る
- 日付(日本時間)+ source をシードにする。投稿済みの作品(`upload_history.json`)は選ばない
- パブリックドメイン(CC0)以外の画像は使わない。AIC の `description`(CC-BY)は取得しない
- レート制限: Met は1秒5回まで、AIC は1.1秒に1回まで。429・5xx(Met は一時的な 403 も)は待って再試行する
- `User-Agent` / `AIC-User-Agent` は環境変数 `ART_SHORTS_USER_AGENT` で変えられる(連絡先を入れておくとよい)

## クイズ(縦型の既定、`quiz.py`)

「When was this painted?」の3択。全部データから自動で作るので、解説文はいらない。

| 秒 | 画面 |
|---|---|
| 0〜0.5 | 絵の一部を画面いっぱいに映す(最初のコマから問いを表示)。顔があれば顔、なければ目立つところを自動で選ぶ |
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
- 冒頭で拡大する場所: OpenCV の顔検出(YuNet、`models/`、MIT ライセンス)で顔を探し、いちばん目立つ顔
  (大きさ・確からしさ・中央寄り)を、顔が範囲の幅の約4割・上寄りになるように映す。確からしさ0.7未満や、
  小さすぎる顔(群衆の中の顔など)は使わない。顔がなければ、周りと違うところ(spectral residual)・色の鮮やかさ・
  模様の細かさを合わせた「目立つ部分」がいちばん多く入る範囲を映す

## 読み上げ(`narration.py`)

クイズは英語で読み上げる。台本は作品データだけから作り、声の長さに合わせて画面の場面の時刻を決める
(選択肢は読み上げに合わせて1つずつ出て、「It's 1889!」と同時に正解が光る)。長さは17〜19秒ほど
(2026-11-05、`en-US-Chirp3-HD-Charon`・1.1倍速で確認)。60文字を超える題名は読まず、作者だけ読む(題名は画面に出る)。

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

- 声は `ART_SHORTS_TTS_VOICE`(既定 `en-US-Chirp3-HD-Charon`。9種類を聞き比べて選んだ)、速さは `ART_SHORTS_TTS_RATE`(既定 1.1)で変えられる。
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

"""題名と説明の翻訳(YouTube の localizations)。視聴者の言語が日本語・スペイン語・フランス語・ドイツ語・ポルトガル語なら、
その言語の題名と説明が表示される。Wait, That Big?(2000Re/wait-that-big の locales.py)と同じ仕組み。AI は使わない。

題名の型(art_shorts.TITLES)ごとの訳。画家の名前と作品名は英語のまま入れる(美術館のデータのまま)。
答え(年)は題名に書かない。説明は、その言語の1行目のあとに英語の説明(選択肢・答え・出典)をそのまま続ける。
フランス語は画家の性別で形が変わらない言い方にしている(「a-t-il peint」ではなく「a peint」など)。
"""
LANGS = ["ja", "es", "fr", "de", "pt"]

TITLES = {
    "classic": {
        "ja": "この絵が描かれたのはいつ？🎨 毎日の名画クイズ",
        "es": "¿Cuándo se pintó este cuadro? 🎨 Quiz de arte diario",
        "fr": "Quand ce tableau a-t-il été peint ? 🎨 Quiz d'art quotidien",
        "de": "Wann wurde dieses Bild gemalt? 🎨 Tägliches Kunst-Quiz",
        "pt": "Quando este quadro foi pintado? 🎨 Quiz de arte diário",
    },
    "artist": {
        "ja": "{artist}がこの絵を描いたのはいつ？🎨",
        "es": "¿Cuándo pintó {artist} este cuadro? 🎨",
        "fr": "En quelle année {artist} a peint ce tableau ? 🎨",
        "de": "Wann hat {artist} dieses Bild gemalt? 🎨",
        "pt": "Quando {artist} pintou este quadro? 🎨",
    },
    "guess": {
        "ja": "この絵が描かれた年、当てられる？🎨",
        "es": "¿Adivinas cuándo se pintó este cuadro? 🎨",
        "fr": "Devineras-tu quand ce tableau a été peint ? 🎨",
        "de": "Errätst du, wann dieses Bild gemalt wurde? 🎨",
        "pt": "Consegue adivinhar quando este quadro foi pintado? 🎨",
    },
    "artist_but_when": {
        "ja": "{artist}の作品。でも描かれたのはいつ？🎨",
        "es": "Lo pintó {artist}... pero ¿cuándo? 🎨",
        "fr": "Peint par {artist}... mais quand ? 🎨",
        "de": "Gemalt von {artist}... aber wann? 🎨",
        "pt": "Pintado por {artist}... mas quando? 🎨",
    },
    "work": {
        "ja": "名画クイズ：「{work}」が描かれたのはいつ？🎨",
        "es": "Quiz de arte: ¿cuándo se pintó «{work}»? 🎨",
        "fr": "Quiz d'art : en quelle année a été peint « {work} » ? 🎨",
        "de": "Kunst-Quiz: Wann wurde „{work}“ gemalt? 🎨",
        "pt": "Quiz de arte: quando foi pintado “{work}”? 🎨",
    },
    "how_old": {
        "ja": "この絵は何年前のもの？年を当てよう 🎨",
        "es": "¿Cuántos años tiene este cuadro? Adivina el año 🎨",
        "fr": "Quel âge a ce tableau ? Devine l'année 🎨",
        "de": "Wie alt ist dieses Bild? Errate das Jahr 🎨",
        "pt": "Quantos anos tem este quadro? Adivinhe o ano 🎨",
    },
    "artist_year": {
        "ja": "{artist}のこの絵、何年の作品かわかる？🎨",
        "es": "¿Adivinas el año de este cuadro de {artist}? 🎨",
        "fr": "Devineras-tu l'année de ce tableau de {artist} ? 🎨",
        "de": "Errätst du das Jahr dieses Bildes von {artist}? 🎨",
        "pt": "Adivinha o ano deste quadro de {artist}? 🎨",
    },
    "zoom": {
        "ja": "ズームアウトして、描かれた年を当てよう 🎨",
        "es": "Aleja la vista y adivina el año del cuadro 🎨",
        "fr": "On dézoome : devine l'année du tableau 🎨",
        "de": "Rauszoomen und das Jahr des Bildes erraten 🎨",
        "pt": "Afaste o zoom e adivinhe o ano do quadro 🎨",
    },
    "masterpiece": {
        "ja": "{last}の名作。描かれた年を当てよう 🎨",
        "es": "Adivina cuándo se pintó esta obra maestra de {last} 🎨",
        "fr": "Devine l'année de ce chef-d'œuvre de {last} 🎨",
        "de": "Errate, wann dieses Meisterwerk von {last} entstand 🎨",
        "pt": "Adivinhe quando esta obra-prima de {last} foi pintada 🎨",
    },
    "art_lovers": {
        "ja": "アート好きさんへ：この絵の年代、わかる？🎨",
        "es": "Amantes del arte: ¿saben fechar este cuadro? 🎨",
        "fr": "Fans d'art : sauriez-vous dater ce tableau ? 🎨",
        "de": "Für Kunstfans: Könnt ihr dieses Bild datieren? 🎨",
        "pt": "Amantes da arte: sabem datar este quadro? 🎨",
    },
    "work_artist": {
        "ja": "{artist}「{work}」：描かれた年を当てよう 🎨",
        "es": "«{work}» de {artist}: adivina el año 🎨",
        "fr": "« {work} » de {artist} : devine l'année 🎨",
        "de": "„{work}“ von {artist}: Errate das Jahr 🎨",
        "pt": "“{work}” de {artist}: adivinhe o ano 🎨",
    },
    "which_year": {
        "ja": "この絵は何年に描かれた？予想してみて 🎨",
        "es": "¿En qué año se pintó este cuadro? Adivina 🎨",
        "fr": "En quelle année ce tableau a-t-il été peint ? Devine 🎨",
        "de": "In welchem Jahr wurde dieses Bild gemalt? Rate mal 🎨",
        "pt": "Em que ano este quadro foi pintado? Arrisque 🎨",
    },
}

# 「服装から当てる」回(art_shorts.FASHION_TITLES)
TITLES.update({
    "fashion_clothes": {
        "ja": "服だけで、この絵の時代がわかる？👗",
        "es": "¿Puedes fechar este cuadro solo por la ropa? 👗",
        "fr": "Peux-tu dater ce tableau rien qu'aux vêtements ? 👗",
        "de": "Kannst du dieses Bild allein an der Kleidung datieren? 👗",
        "pt": "Consegue datar este quadro só pelas roupas? 👗",
    },
    "fashion_century": {
        "ja": "何世紀の絵？ヒントは服装 🎨",
        "es": "¿Qué siglo? La ropa es la pista 🎨",
        "fr": "Quel siècle ? Les vêtements sont l'indice 🎨",
        "de": "Welches Jahrhundert? Die Kleidung ist der Hinweis 🎨",
        "pt": "Que século? As roupas são a pista 🎨",
    },
    "fashion_detective": {
        "ja": "ファッション探偵へ：この絵は何世紀？👒",
        "es": "Detectives de la moda: ¿de qué siglo es este cuadro? 👒",
        "fr": "Détectives de la mode : de quel siècle est ce tableau ? 👒",
        "de": "Mode-Detektive: Aus welchem Jahrhundert ist dieses Bild? 👒",
        "pt": "Detetives da moda: de que século é este quadro? 👒",
    },
})

# 浮世絵の回(art_shorts.UKIYOE_TITLES)。版画なので「描いた」ではなく「作られた」
TITLES.update({
    "ukiyoe_when": {
        "ja": "この浮世絵が作られたのはいつ？🎨",
        "es": "¿Cuándo se hizo esta estampa japonesa? 🎨",
        "fr": "Quand cette estampe japonaise a-t-elle été faite ? 🎨",
        "de": "Wann entstand dieser japanische Holzschnitt? 🎨",
        "pt": "Quando foi feita esta gravura japonesa? 🎨",
    },
    "ukiyoe_artist": {
        "ja": "{artist}のこの浮世絵、作られたのはいつ？🎨",
        "es": "¿Cuándo hizo {artist} esta estampa? 🎨",
        "fr": "Quand {artist} a fait cette estampe ? 🎨",
        "de": "Wann schuf {artist} diesen Holzschnitt? 🎨",
        "pt": "Quando {artist} fez esta gravura? 🎨",
    },
    "ukiyoe_guess": {
        "ja": "浮世絵クイズ：この版画が作られた年を当てよう 🗾",
        "es": "Quiz de ukiyo-e: adivina el año de esta estampa 🗾",
        "fr": "Quiz ukiyo-e : devine l'année de cette estampe 🗾",
        "de": "Ukiyo-e-Quiz: Errate das Jahr dieses Holzschnitts 🗾",
        "pt": "Quiz de ukiyo-e: adivinhe o ano desta gravura 🗾",
    },
})

UKIYOE_LEAD = {
    "ja": "浮世絵(木版画)が作られた年を当てるクイズです。答えが出る前に予想してみてね！🎨",
    "es": "Un quiz para adivinar el año de estampas japonesas (ukiyo-e). ¡Adivina antes de la respuesta! 🎨",
    "fr": "Un quiz pour dater des estampes japonaises (ukiyo-e). Devine avant la réponse ! 🎨",
    "de": "Ein Quiz: Wann entstanden japanische Holzschnitte (Ukiyo-e)? Rate vor der Auflösung! 🎨",
    "pt": "Um quiz para adivinhar o ano de gravuras japonesas (ukiyo-e). Adivinhe antes da resposta! 🎨",
}

FASHION_LEAD = {
    "ja": "服装を手がかりに、描かれた世紀を当てるクイズです。何が決め手になったか、コメントで教えてね！👗",
    "es": "Un quiz para adivinar el siglo de un cuadro por la ropa. ¡Cuéntanos qué pista te ayudó! 👗",
    "fr": "Un quiz pour deviner le siècle d'un tableau grâce aux vêtements. Dis-nous quel indice t'a aidé ! 👗",
    "de": "Ein Quiz: Errate das Jahrhundert eines Gemäldes an der Kleidung. Welcher Hinweis hat dir geholfen? 👗",
    "pt": "Um quiz para adivinhar o século de um quadro pelas roupas. Conte qual pista ajudou você! 👗",
}

LEAD = {
    "ja": "答えが出る前に、描かれた年を予想してみてね！🎨 名画の制作年を当てるクイズです。",
    "es": "¡Adivina el año antes de la respuesta! 🎨 Un quiz para adivinar cuándo se pintaron obras famosas.",
    "fr": "Devine l'année avant la réponse ! 🎨 Un quiz pour dater des tableaux célèbres.",
    "de": "Rate das Jahr vor der Auflösung! 🎨 Ein Quiz: Wann wurden berühmte Gemälde gemalt?",
    "pt": "Adivinhe o ano antes da resposta! 🎨 Um quiz para descobrir quando quadros famosos foram pintados.",
}


def _yt(s):
    return s.replace("<", "‹").replace(">", "›")


def build(style, number, vals, description_en, fashion=False, ukiyoe=False):
    """{言語: {"title", "description"}}。vals は art_shorts.title_vals() の値。埋められない言語・型は入れない。"""
    if style not in TITLES:
        return {}
    out = {}
    for lang in LANGS:
        v2 = dict(vals)
        if ukiyoe and lang == "ja" and v2.get("artist"):
            import ukiyoe as U
            v2["artist"] = U.JA_NAMES.get(v2["artist"], v2["artist"])       # 日本語では漢字の名前(葛飾北斎など)
        try:
            t = TITLES[style][lang].format(**{k: v for k, v in v2.items() if v})
        except KeyError:
            continue
        title = f"[{number}] {t}"
        if len(title) > 100:
            continue
        out[lang] = {"title": _yt(title), "description": _yt((UKIYOE_LEAD if ukiyoe else FASHION_LEAD if fashion else LEAD)[lang] + "\n\n" + description_en)[:4900]}
    return out

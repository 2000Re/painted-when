"""クイズに使う「有名な画家」のリスト。

各項目は (検索語, 一致に必要な語)。美術館の作者名(アクセントを外して小文字にしたもの)に、
「一致に必要な語」がすべて含まれる作品だけを、その画家の作品とみなす。
同じ姓の別人を拾わないよう、よくある姓は名前も含める(例: Millet は Jean-François Millet だけ)。

「工房」「追随者」「〜風」「〜の模写」など、本人以外の作品は使わない(is_attributed_only)。
2026-11 に Met とシカゴ美術館で数えたところ、クイズに使える作品は64人で約740点あった
(1日2本で約1年分)。
"""
import re
import unicodedata

FAMOUS = [
    # ルネサンス〜バロック
    ("Jan van Eyck", ["eyck"]),
    ("Rogier van der Weyden", ["weyden"]),
    ("Hieronymus Bosch", ["bosch", "hieronymus"]),
    ("Fra Angelico", ["angelico"]),
    ("Andrea Mantegna", ["mantegna"]),
    ("Giovanni Bellini", ["giovanni", "bellini"]),
    ("Sandro Botticelli", ["botticelli"]),
    ("Raphael", ["raphael"]),
    ("Titian", ["titian"]),
    ("Tintoretto", ["tintoretto"]),
    ("Paolo Veronese", ["veronese"]),
    ("Albrecht Dürer", ["durer"]),
    ("Hans Holbein the Younger", ["holbein"]),
    ("Pieter Bruegel", ["bruegel"]),
    ("El Greco", ["el greco"]),
    ("Caravaggio", ["caravaggio"]),
    ("Peter Paul Rubens", ["rubens"]),
    ("Anthony van Dyck", ["dyck", "anthony"]),
    ("Frans Hals", ["frans", "hals"]),
    ("Rembrandt", ["rembrandt"]),
    ("Johannes Vermeer", ["vermeer"]),
    ("Diego Velázquez", ["velazquez"]),
    ("Francisco de Zurbarán", ["zurbaran"]),
    ("Bartolomé Esteban Murillo", ["murillo"]),
    ("Georges de La Tour", ["georges", "la tour"]),
    ("Nicolas Poussin", ["poussin"]),
    ("Claude Lorrain", ["claude lorrain"]),
    ("Artemisia Gentileschi", ["artemisia"]),
    # 18世紀
    ("Antoine Watteau", ["watteau"]),
    ("François Boucher", ["boucher", "francois"]),
    ("Jean-Honoré Fragonard", ["fragonard"]),
    ("Canaletto", ["canaletto"]),
    ("Giovanni Battista Tiepolo", ["tiepolo"]),
    ("Thomas Gainsborough", ["gainsborough"]),
    ("Joshua Reynolds", ["joshua", "reynolds"]),
    ("Jean-Baptiste-Siméon Chardin", ["chardin"]),
    ("Élisabeth Louise Vigée Le Brun", ["vigee le brun"]),
    ("Francisco de Goya", ["goya"]),
    ("Jacques Louis David", ["jacques", "louis", "david"]),
    ("Gilbert Stuart", ["gilbert", "stuart"]),
    # 19世紀
    ("Jean-Auguste-Dominique Ingres", ["ingres"]),
    ("Eugène Delacroix", ["delacroix"]),
    ("Théodore Géricault", ["gericault"]),
    ("Caspar David Friedrich", ["caspar", "friedrich"]),
    ("J. M. W. Turner", ["mallord", "turner"]),
    ("John Constable", ["john", "constable"]),
    ("Camille Corot", ["corot"]),
    ("Jean-François Millet", ["jean", "francois", "millet"]),
    ("Gustave Courbet", ["courbet"]),
    ("Rosa Bonheur", ["rosa", "bonheur"]),
    ("Thomas Cole", ["thomas", "cole"]),
    ("Frederic Edwin Church", ["frederic", "church"]),
    ("Albert Bierstadt", ["bierstadt"]),
    ("Winslow Homer", ["winslow", "homer"]),
    ("Thomas Eakins", ["eakins"]),
    ("James McNeill Whistler", ["whistler"]),
    ("John Singer Sargent", ["singer", "sargent"]),
    ("Mary Cassatt", ["cassatt"]),
    ("Édouard Manet", ["edouard", "manet"]),
    ("Claude Monet", ["claude", "monet"]),
    ("Pierre-Auguste Renoir", ["renoir", "auguste"]),
    ("Edgar Degas", ["degas"]),
    ("Camille Pissarro", ["camille", "pissarro"]),
    ("Alfred Sisley", ["sisley"]),
    ("Berthe Morisot", ["morisot"]),
    ("Gustave Caillebotte", ["caillebotte"]),
    ("Paul Cézanne", ["cezanne"]),
    ("Georges Seurat", ["seurat"]),
    ("Paul Signac", ["signac"]),
    ("Vincent van Gogh", ["gogh"]),
    ("Paul Gauguin", ["gauguin"]),
    ("Henri de Toulouse-Lautrec", ["toulouse-lautrec"]),
    ("Henri Rousseau", ["henri", "rousseau"]),
    ("Gustave Moreau", ["gustave", "moreau"]),
    ("Odilon Redon", ["redon"]),
    ("Pierre Puvis de Chavannes", ["puvis de chavannes"]),
    ("Dante Gabriel Rossetti", ["rossetti"]),
    ("John William Waterhouse", ["waterhouse"]),
    ("William-Adolphe Bouguereau", ["bouguereau"]),
    ("Jean-Léon Gérôme", ["gerome"]),
    ("Arnold Böcklin", ["bocklin"]),
    # 20世紀初め(パブリックドメインのものだけが残る)
    ("Gustav Klimt", ["klimt"]),
    ("Egon Schiele", ["schiele"]),
    ("Edvard Munch", ["munch"]),
    ("Amedeo Modigliani", ["modigliani"]),
    ("Pierre Bonnard", ["bonnard"]),
    ("Édouard Vuillard", ["vuillard"]),
    ("Childe Hassam", ["hassam"]),
    ("William Merritt Chase", ["merritt chase"]),
]

# 本人以外の作品を表す言い方(作者名の頭や、Met の artistPrefix に入る)
ATTRIBUTION_WORDS = ("workshop", "follower", "circle", "style of", "school of", "after", "copy",
                     "manner of", "studio", "imitator", "attributed", "pupil", "assistant", "possibly")


def normalize(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", s)


def matches(artist, required):
    a = normalize(artist)
    return all(w in a for w in required)


def is_attributed_only(artist_text, prefix=""):
    """「工房」「追随者」など、本人の作品ではないことを示す言い方があれば True。"""
    p = normalize(prefix).strip()
    if p:
        return True
    a = normalize(artist_text)
    head = a.split("(")[0]
    return any(head.startswith(w) or f" {w} " in f" {head} " for w in ATTRIBUTION_WORDS) or " and workshop" in a


def find(artist, prefix=""):
    """作者名がリストの画家なら、その検索語を返す(本人の作品でなければ None)。"""
    if is_attributed_only(artist, prefix):
        return None
    for name, required in FAMOUS:
        if matches(artist, required):
            return name
    return None

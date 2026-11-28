"""サイト(docs/)の作品画像が開けるかを確かめ、開けないものは美術館の API から今の画像の URL を取り直す。

美術館が画像を差し替えると、保存していた URL が 404 になる(2026-11-29 に #14 で起きた。シカゴ美術館の image_id が
変わっていた)。.github/workflows/site-images.yml から週1回動かす。直したら docs/data/quizzes.json を書き換えて
site_gen.py でページを作り直す(コミットはワークフローがする)。

美術館に負荷をかけないよう、1件ずつ間をあけて取りに行く(画像1枚につき1回。開けないときだけ API に1回)。
一時的な失敗(429・5xx・Met の 403)では書き換えない。新しい URL が実際に開けたときだけ書き換える。
標準ライブラリだけで書く(GitHub Actions で外部ライブラリなしに動かすため)。

使い方: python site_images.py          確かめて、直せるものは直す
        python site_images.py --check  確かめるだけ(書き換えない)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import site_gen

UA = os.environ.get("ART_SHORTS_USER_AGENT", "art-shorts/0.1 (daily public-domain painting video)")
GAP = 1.1           # 取りに行く間隔(秒)


def status(url, headers=None):
    """GET して HTTP の状態コード(通信エラーは 0)。"""
    time.sleep(GAP)
    h = {"User-Agent": UA, "Accept": "*/*", **(headers or {})}
    url = urllib.parse.quote(url, safe=":/?&=%#+,;@~!$'()*")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
            r.read(1024)
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0


def get_json(url, headers=None):
    time.sleep(GAP)
    h = {"User-Agent": UA, **(headers or {})}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        return json.loads(r.read())


def current_image(x):
    """美術館の API から、今の画像の URL。取れなければ None。"""
    try:
        if x["source"] == "aic":
            d = get_json(f"https://api.artic.edu/api/v1/artworks/{x['id']}?fields=id,image_id,is_public_domain",
                         {"AIC-User-Agent": UA})
            data, iiif = d.get("data") or {}, ((d.get("config") or {}).get("iiif_url") or "").rstrip("/")
            if data.get("is_public_domain") is True and data.get("image_id") and iiif:
                return f"{iiif}/{data['image_id']}/full/843,/0/default.jpg"
        elif x["source"] == "met":
            o = get_json(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{x['id']}")
            if o.get("isPublicDomain") is True:
                return o.get("primaryImageSmall") or o.get("primaryImage") or None
    except Exception as e:
        print(f"  #{x['number']}: API から取れません({e})", file=sys.stderr)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="確かめるだけ(書き換えない)")
    args = ap.parse_args()
    entries = site_gen.load()
    fixed, broken = [], []
    for x in entries:
        code = status(x["image"])
        if code == 200:
            continue
        print(f"#{x['number']} {x['title']}: 画像が開けません(HTTP {code or '通信エラー'})")
        if code in (0, 429) or code >= 500 or (code == 403 and x["source"] == "met"):
            print("  一時的な失敗かもしれないので、今回は書き換えません")
            broken.append(x["number"])
            continue
        new = current_image(x)
        if new and new != x["image"] and status(new) == 200:
            print(f"  新しい画像: {new}")
            if not args.check:
                x["image"] = new
            fixed.append(x["number"])
        else:
            print("  美術館の今の画像も取れませんでした(サイトでは「画像を表示できません」と出ます)")
            broken.append(x["number"])
    if fixed and not args.check:
        site_gen.save(entries)
        site_gen.build()
    print(f"確かめた: {len(entries)} 件 / 直した: {fixed or 'なし'} / 直せなかった: {broken or 'なし'}")


if __name__ == "__main__":
    main()

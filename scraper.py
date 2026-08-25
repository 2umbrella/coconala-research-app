"""ココナラのSSRページから埋め込みデータ(__NUXT__)を取得・パースするモジュール。

ココナラはNuxt.jsのサーバーサイドレンダリングを使っており、
検索結果・カテゴリ・サービス詳細の構造化データがHTML内の
`window.__NUXT__=(function(...){...})(...)` に埋め込まれている。
HTMLのクラス名パースよりも仕様変更に強いため、これを利用する。
JS関数式のままなので quickjs で評価してJSONに変換する。
"""

from __future__ import annotations

import json
import re
import time

import quickjs
import requests

BASE_URL = "https://coconala.com"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 現行のソート指定（sort_byクエリの値）
SORT_OPTIONS = {
    "おすすめ順": "recommend",
    "新着順": "new",
    "ランキング": "ranking",
    "お気に入り数順": "fav",
}

REQUEST_INTERVAL_SEC = 1.0  # 連続アクセスの間隔（サーバー負荷への配慮）

_NUXT_RE = re.compile(r"window\.__NUXT__=(.*?)</script>", re.DOTALL)


class ScrapeError(Exception):
    """取得やパースに失敗したときの例外（UI側で表示するメッセージを持つ）。"""


def fetch_html(url: str, session: requests.Session | None = None) -> str:
    ses = session or requests
    try:
        res = ses.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    except requests.RequestException as e:
        raise ScrapeError(f"ページの取得に失敗しました: {url} ({e})") from e
    if res.status_code != 200:
        raise ScrapeError(
            f"ページの取得に失敗しました（HTTP {res.status_code}）: {url}\n"
            "アクセスが制限されている可能性があります。時間を置いて再実行してください。"
        )
    return res.text


def parse_nuxt(html: str) -> dict:
    m = _NUXT_RE.search(html)
    if not m:
        raise ScrapeError(
            "ページ内にデータ(__NUXT__)が見つかりませんでした。"
            "ココナラ側の仕様が変わった可能性があります。"
        )
    expr = m.group(1).rstrip().rstrip(";")
    try:
        ctx = quickjs.Context()
        return json.loads(ctx.eval("JSON.stringify(" + expr + ")"))
    except Exception as e:
        raise ScrapeError(f"埋め込みデータの解析に失敗しました: {e}") from e


# ---------------------------------------------------------------------------
# カテゴリ一覧（動的取得。ハードコードだと陳腐化するため）
# ---------------------------------------------------------------------------

def get_category_tree() -> list[dict]:
    """現在のカテゴリツリーを取得する。

    Returns: [{"id": 3, "name": "占い", "subCategories": [{"id": 656, "name": "恋愛"}, ...]}, ...]
    """
    html = fetch_html(f"{BASE_URL}/categories")
    nuxt = parse_nuxt(html)
    try:
        cats = nuxt["state"]["master"]["masterCategories"]
    except (KeyError, TypeError) as e:
        raise ScrapeError("カテゴリ一覧の取得に失敗しました。") from e
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "subCategories": [
                {"id": s["id"], "name": s["name"]} for s in c.get("subCategories", [])
            ],
        }
        for c in cats
    ]


# ---------------------------------------------------------------------------
# 検索（キーワード / カテゴリ）
# ---------------------------------------------------------------------------

def _build_search_url(
    keyword: str | None,
    category_id: int | None,
    sort_by: str,
    page: int,
) -> str:
    if keyword:
        kw = requests.utils.quote(keyword)
        return f"{BASE_URL}/search?keyword={kw}&sort_by={sort_by}&page={page}"
    return f"{BASE_URL}/categories/{category_id}?sort_by={sort_by}&page={page}"


def _extract_search_results(nuxt: dict) -> tuple[list[dict], int]:
    try:
        search = nuxt["state"]["pages"]["search"]["search"]
        items = search["searchResultsList"]
        total = search.get("total", 0)
    except (KeyError, TypeError) as e:
        raise ScrapeError(
            "検索結果データの構造が想定と異なります。"
            "ココナラ側の仕様が変わった可能性があります。"
        ) from e
    return items, total


def _row_from_search_item(item: dict) -> dict:
    s = item.get("service", {})
    p = item.get("provider", {})
    ratings = s.get("ratings") or {}
    images = s.get("serviceImagesList") or []
    image_path = images[0].get("imagePath", "") if images else ""
    service_id = s.get("id")
    return {
        "サービスID": service_id,
        "タイトル": s.get("overview", ""),
        "キャッチコピー": s.get("catchphrase", ""),
        "価格": s.get("priceWot"),
        "販売実績": s.get("performanceCount"),
        "評価": ratings.get("indicator"),
        "評価件数": ratings.get("ratingCount"),
        "大カテゴリ": s.get("masterParentCategoryName", ""),
        "小カテゴリ": s.get("masterChildCategoryName", ""),
        "カテゴリ種別": s.get("masterCategoryTypeName", ""),
        "出品者": p.get("name", ""),
        "出品者ランク": p.get("level"),
        "PRO認定": bool(p.get("proFlag")),
        "URL": f"{BASE_URL}/services/{service_id}" if service_id else "",
        "画像URL": (
            f"https://service-cdn.coconala.com/crop/460/380{image_path}"
            if image_path
            else ""
        ),
        "冒頭文": s.get("head", ""),
    }


def search_services(
    keyword: str | None = None,
    category_id: int | None = None,
    sort_by: str = "recommend",
    pages: int = 2,
    progress_callback=None,
) -> tuple[list[dict], int]:
    """検索結果を複数ページ取得して行データのリストと総件数を返す。

    keyword が指定されていればキーワード検索、なければ category_id のカテゴリ検索。
    """
    if not keyword and not category_id:
        raise ScrapeError("キーワードかカテゴリのどちらかを指定してください。")

    session = requests.Session()
    rows: list[dict] = []
    seen_ids: set = set()
    total = 0
    for page in range(1, pages + 1):
        if progress_callback:
            progress_callback(f"検索結果 {page}/{pages} ページ目を取得中…", (page - 1) / pages)
        url = _build_search_url(keyword, category_id, sort_by, page)
        nuxt = parse_nuxt(fetch_html(url, session))
        items, total = _extract_search_results(nuxt)
        if not items:
            break
        for item in items:
            row = _row_from_search_item(item)
            if row["サービスID"] in seen_ids:
                continue
            seen_ids.add(row["サービスID"])
            rows.append(row)
        if page < pages:
            time.sleep(REQUEST_INTERVAL_SEC)
    if progress_callback:
        progress_callback("検索結果の取得が完了しました", 1.0)
    return rows, total


# ---------------------------------------------------------------------------
# サービス詳細（お気に入り数・本文・オプション・よくある質問など）
# ---------------------------------------------------------------------------

def get_service_detail(service_id: int, session: requests.Session | None = None) -> dict:
    html = fetch_html(f"{BASE_URL}/services/{service_id}", session)
    nuxt = parse_nuxt(html)
    try:
        d = nuxt["state"]["pages"]["services"]["serviceDetail"]["serviceDetail"]
    except (KeyError, TypeError) as e:
        raise ScrapeError(f"サービス詳細の取得に失敗しました (ID: {service_id})") from e

    options = "\n".join(
        f"{o.get('title', o.get('name', ''))} +{o.get('price', '')}円"
        for o in (d.get("optionsList") or [])
    )
    faqs = "\n".join(
        f"Q. {f.get('question', '')}\nA. {f.get('answer', '')}"
        for f in (d.get("faqsList") or [])
    )
    return {
        "サービスID": d.get("id"),
        "お気に入り数": d.get("favCount"),
        "本文": d.get("body", ""),
        "お届け日数": d.get("deliveryTime", ""),
        "オプション": options,
        "よくある質問": faqs,
        "掲載開始日": d.get("openedDate", ""),
    }


def enrich_with_details(
    rows: list[dict],
    limit: int,
    progress_callback=None,
) -> list[dict]:
    """検索結果の先頭 limit 件について詳細ページの情報を付加する。"""
    session = requests.Session()
    targets = rows[:limit]
    for i, row in enumerate(targets):
        if progress_callback:
            progress_callback(
                f"詳細ページを取得中… {i + 1}/{len(targets)} 件目", (i + 1) / len(targets)
            )
        try:
            detail = get_service_detail(row["サービスID"], session)
            row.update({k: v for k, v in detail.items() if k != "サービスID"})
        except ScrapeError:
            # 個別の失敗（非公開化など）はスキップして続行
            pass
        time.sleep(REQUEST_INTERVAL_SEC * 0.7)
    return rows

"""ココナラ競合分析＋テキストマイニング Webアプリ（Streamlit版）。

旧Google Colabノートブックの置き換え。
- Selenium不要（SSRページ埋め込みデータを直接パース）
- カテゴリ一覧はココナラから動的取得（陳腐化しない）
- テキストマイニングはアプリ内で完結（UserLocal用CSVの出力も可能）
"""

import io
import os

import pandas as pd
import streamlit as st

import mining
import scraper
from scraper import ScrapeError

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "ipaexg.ttf")

st.set_page_config(page_title="ココナラ競合分析ツール", page_icon="🔎", layout="wide")

st.title("🔎 ココナラ競合分析＋テキストマイニング")
st.caption(
    "キーワードまたはカテゴリでココナラの出品サービスを収集し、"
    "価格・販売実績の分析と、タイトル・キャッチコピーのテキストマイニングを行います。"
)


# ---------------------------------------------------------------------------
# カテゴリ一覧（24時間キャッシュ）
# ---------------------------------------------------------------------------

@st.cache_data(ttl=24 * 3600, show_spinner="カテゴリ一覧を取得中…")
def load_categories():
    return scraper.get_category_tree()


@st.cache_data(ttl=3600, show_spinner=False)
def cached_search(keyword, category_id, sort_by, pages):
    return scraper.search_services(
        keyword=keyword, category_id=category_id, sort_by=sort_by, pages=pages
    )


# ---------------------------------------------------------------------------
# サイドバー：検索条件
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("検索条件")

    mode = st.radio("検索方法", ["キーワードで検索", "カテゴリで検索"])

    keyword = None
    category_id = None
    category_label = ""

    if mode == "キーワードで検索":
        keyword = st.text_input("検索キーワード", placeholder="例：占い、ロゴ作成、動画編集")
        category_label = keyword or ""
    else:
        try:
            categories = load_categories()
        except ScrapeError as e:
            st.error(str(e))
            st.stop()
        parent_names = [c["name"] for c in categories]
        parent_name = st.selectbox("大カテゴリ", parent_names)
        parent = next(c for c in categories if c["name"] == parent_name)
        sub_options = ["（大カテゴリ全体）"] + [s["name"] for s in parent["subCategories"]]
        sub_name = st.selectbox("小カテゴリ", sub_options)
        if sub_name == "（大カテゴリ全体）":
            category_id = parent["id"]
            category_label = parent_name
        else:
            sub = next(s for s in parent["subCategories"] if s["name"] == sub_name)
            category_id = sub["id"]
            category_label = f"{parent_name} > {sub_name}"

    sort_name = st.selectbox("並び順", list(scraper.SORT_OPTIONS.keys()))
    pages = st.slider("取得ページ数（1ページ≒60件）", 1, 5, 2)

    st.divider()
    with_details = st.checkbox(
        "詳細ページも取得する（お気に入り数・本文など）", value=False,
        help="1件ずつアクセスするため時間がかかります（1件あたり約1〜2秒）",
    )
    detail_limit = 30
    if with_details:
        detail_limit = st.slider("詳細を取得する件数（上位から）", 10, 120, 30, step=10)

    run = st.button("🚀 分析を実行", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------

if run:
    if mode == "キーワードで検索" and not (keyword and keyword.strip()):
        st.warning("検索キーワードを入力してください。")
        st.stop()

    sort_by = scraper.SORT_OPTIONS[sort_name]
    progress = st.progress(0.0, text="検索を開始します…")

    try:
        rows, total = cached_search(
            keyword.strip() if keyword else None, category_id, sort_by, pages
        )
        if with_details and rows:
            def cb(msg, ratio):
                progress.progress(ratio, text=msg)
            rows = scraper.enrich_with_details(rows, detail_limit, progress_callback=cb)
    except ScrapeError as e:
        progress.empty()
        st.error(str(e))
        st.stop()

    progress.empty()

    if not rows:
        st.warning("検索結果が0件でした。条件を変えてお試しください。")
        st.stop()

    st.session_state["result"] = {
        "rows": rows,
        "total": total,
        "label": category_label,
        "sort": sort_name,
    }

# ---------------------------------------------------------------------------
# 結果表示（rerun後も保持）
# ---------------------------------------------------------------------------

if "result" not in st.session_state:
    st.info("左のサイドバーで検索条件を設定して「分析を実行」を押してください。")
    st.stop()

result = st.session_state["result"]
df = pd.DataFrame(result["rows"])

st.success(
    f"「{result['label']}」（{result['sort']}）：全 {result['total']:,} 件中 "
    f"{len(df)} 件を取得しました"
)

# ---- サマリー指標 ----
c1, c2, c3, c4 = st.columns(4)
price = pd.to_numeric(df["価格"], errors="coerce")
sold = pd.to_numeric(df["販売実績"], errors="coerce")
c1.metric("取得件数", f"{len(df)} 件")
c2.metric("平均価格", f"{price.mean():,.0f} 円" if price.notna().any() else "-")
c3.metric("価格中央値", f"{price.median():,.0f} 円" if price.notna().any() else "-")
c4.metric("平均販売実績", f"{sold.mean():,.1f} 件" if sold.notna().any() else "-")

tab_data, tab_mining, tab_price, tab_dl = st.tabs(
    ["📋 データ一覧", "📝 テキストマイニング", "💰 価格・実績分析", "⬇️ ダウンロード"]
)

# ---- データ一覧 ----
with tab_data:
    # サムネイルを見やすいよう画像列を先頭付近に配置し、行の高さを確保する
    front_cols = ["画像URL", "タイトル", "キャッチコピー", "価格", "販売実績", "評価"]
    col_order = [c for c in front_cols if c in df.columns] + [
        c for c in df.columns if c not in front_cols
    ]
    st.dataframe(
        df[col_order],
        use_container_width=True,
        height=600,
        row_height=76,
        column_config={
            "URL": st.column_config.LinkColumn("URL"),
            "画像URL": st.column_config.ImageColumn("サムネイル", width="medium"),
        },
    )
    st.caption("サムネイルをクリックすると拡大表示できます。")

# ---- テキストマイニング ----
with tab_mining:
    text_source = st.radio(
        "分析対象テキスト",
        ["タイトル＋キャッチコピー", "タイトルのみ", "本文（詳細取得時のみ）"],
        horizontal=True,
    )
    if text_source == "タイトルのみ":
        texts = df["タイトル"].fillna("").tolist()
    elif text_source == "本文（詳細取得時のみ）":
        if "本文" not in df.columns:
            st.warning("本文を分析するには「詳細ページも取得する」を有効にして再実行してください。")
            st.stop()
        texts = df["本文"].fillna("").tolist()
    else:
        texts = (df["タイトル"].fillna("") + " " + df["キャッチコピー"].fillna("")).tolist()

    with st.spinner("形態素解析中…"):
        docs = mining.extract_words(texts)

    freq = mining.word_frequency(docs, top_n=50)
    if not freq:
        st.warning("分析対象の単語が見つかりませんでした。")
        st.stop()

    col_wc, col_freq = st.columns([3, 2])

    with col_wc:
        st.subheader("ワードクラウド")
        try:
            wc = mining.build_wordcloud(dict(freq), FONT_PATH)
            st.image(wc.to_array(), use_container_width=True)
        except Exception as e:
            st.error(f"ワードクラウドの生成に失敗しました: {e}")

    with col_freq:
        st.subheader("頻出単語 TOP30")
        freq_df = pd.DataFrame(freq[:30], columns=["単語", "出現回数"])
        st.dataframe(freq_df, use_container_width=True, height=420, hide_index=True)

    st.subheader("よく使われる単語の組み合わせ")
    col_bi, col_co = st.columns(2)
    with col_bi:
        st.caption("連続して使われる単語ペア（フレーズの傾向）")
        bi = mining.bigram_frequency(docs, top_n=20)
        st.dataframe(
            pd.DataFrame(bi, columns=["単語ペア", "出現回数"]),
            use_container_width=True, hide_index=True,
        )
    with col_co:
        st.caption("同じサービス内で一緒に使われる単語ペア（共起）")
        co = mining.cooccurrence(docs, top_n=20)
        st.dataframe(
            pd.DataFrame(co, columns=["単語ペア", "共起回数"]),
            use_container_width=True, hide_index=True,
        )

# ---- 価格・実績分析 ----
with tab_price:
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("価格帯の分布")
        if price.notna().any():
            bins = [0, 1000, 3000, 5000, 10000, 30000, 50000, 100000, float("inf")]
            labels = ["〜1千", "1〜3千", "3〜5千", "5千〜1万", "1〜3万", "3〜5万", "5〜10万", "10万〜"]
            dist = pd.cut(price, bins=bins, labels=labels).value_counts().reindex(labels)
            st.bar_chart(dist)
    with col_b:
        st.subheader("販売実績 TOP10")
        top_sold = df.nlargest(10, "販売実績")[["タイトル", "価格", "販売実績", "評価", "出品者"]]
        st.dataframe(top_sold, use_container_width=True, hide_index=True)

    st.subheader("価格 × 販売実績")
    chart_df = df[["価格", "販売実績", "タイトル"]].dropna()
    if not chart_df.empty:
        st.scatter_chart(chart_df, x="価格", y="販売実績")

# ---- ダウンロード ----
with tab_dl:
    st.subheader("データのダウンロード")

    csv_utf8 = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📄 全データCSV（Excel対応 / UTF-8 BOM）",
        csv_utf8, "coconala_data.csv", "text/csv",
        use_container_width=True,
    )

    excel_buf = io.BytesIO()
    df.to_excel(excel_buf, index=False, engine="openpyxl")
    st.download_button(
        "📊 全データExcel（.xlsx）",
        excel_buf.getvalue(), "coconala_data.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.divider()
    st.subheader("UserLocalテキストマイニングを使いたい場合")
    st.markdown(
        "以下のCSVをダウンロードして "
        "[UserLocal テキストマイニング](https://textmining.userlocal.jp/) に"
        "手動でアップロードすると、共起ネットワークなど高度な分析ができます。"
    )
    ul_df = df[["タイトル", "キャッチコピー"]]
    ul_csv = ul_df.to_csv(index=False).encode("cp932", errors="replace")
    st.download_button(
        "📝 UserLocal用CSV（Shift-JIS）",
        ul_csv, "buzzword.csv", "text/csv",
        use_container_width=True,
    )

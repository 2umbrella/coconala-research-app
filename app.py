"""ココナラ競合分析＋テキストマイニング Webアプリ（Streamlit版）。

旧Google Colabノートブックの置き換え。
- Selenium不要（SSRページ埋め込みデータを直接パース）
- カテゴリ一覧はココナラから動的取得（陳腐化しない）
- テキストマイニングはアプリ内で完結（UserLocal用CSVの出力も可能）
"""

import io
import os

import altair as alt
import pandas as pd
import streamlit as st

import mining
import scraper
from scraper import ScrapeError

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "ipaexg.ttf")

# 実際の合言葉は Streamlit Secrets の access_code に置く（Settings > Secrets）。
# 下の値はSecretsを設定できないローカル開発用のダミーで、本番では使われない。
LOCAL_DEV_ACCESS_CODE = "000000"

st.set_page_config(page_title="ココナラ競合分析ツール", page_icon="🔎", layout="wide")


def _access_code() -> tuple[str, bool]:
    """(合言葉, Secretsから読めたか) を返す。"""
    try:
        return str(st.secrets["access_code"]), True
    except Exception:
        return LOCAL_DEV_ACCESS_CODE, False


def require_access_code() -> None:
    """合言葉を入力するまで、以降の画面を表示しない。"""
    if st.session_state.get("authorized"):
        return

    expected, from_secrets = _access_code()

    st.title("🔒 ココナラ競合分析ツール")
    st.write("ご利用には合言葉（数字）が必要です。")
    with st.form("access"):
        code = st.text_input("合言葉", type="password", placeholder="数字を入力")
        submitted = st.form_submit_button("開く", type="primary")
    if submitted:
        if code.strip() == expected:
            st.session_state["authorized"] = True
            st.rerun()
        else:
            st.error("合言葉が違います。")
    if not from_secrets:
        st.warning(
            "合言葉が未設定です（開発用のダミーで動作しています）。"
            "公開して使う場合は Settings > Secrets に access_code を登録してください。"
        )
    st.stop()


require_access_code()

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
        "詳細ページも取得する（推奨）", value=True,
        help=(
            "サービス内容の全文・お気に入り数・オプション・よくある質問を取得します。"
            "検索結果だけでは、サービス内容は冒頭100文字ほどで打ち切られます。"
            "1件ずつアクセスするため1件あたり約1秒かかります。"
        ),
    )
    detail_limit = 60
    if with_details:
        detail_limit = st.slider("詳細を取得する件数（上位から）", 10, 300, 60, step=10)
        st.caption(f"詳細取得の目安時間：約 {detail_limit} 秒")

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
        "with_details": with_details,
        "detail_limit": detail_limit if with_details else 0,
    }

# ---------------------------------------------------------------------------
# 結果表示（rerun後も保持）
# ---------------------------------------------------------------------------

if "result" not in st.session_state:
    st.info("左のサイドバーで検索条件を設定して「分析を実行」を押してください。")
    st.stop()

result = st.session_state["result"]
df = pd.DataFrame(result["rows"])

# サービスIDはサービスURLと重複するため表示・出力からは外す（内部の取得処理でのみ使用）
df = df.drop(columns=["サービスID"], errors="ignore")

# 詳細を取得していない行のサービス内容は冒頭のみ。列名でそれが分かるようにする
if not result.get("with_details"):
    df = df.rename(columns={"サービス内容": "サービス内容（冒頭のみ）"})

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
    front_cols = [
        "画像URL", "タイトル", "キャッチコピー", "価格", "販売実績",
        "評価", "評価件数", "お気に入り数", "出品者", "サービスURL",
    ]
    col_order = [c for c in front_cols if c in df.columns] + [
        c for c in df.columns if c not in front_cols
    ]
    st.dataframe(
        df[col_order],
        use_container_width=True,
        height=600,
        row_height=76,
        column_config={
            "サービスURL": st.column_config.LinkColumn("サービスURL", display_text="開く"),
            "画像URL": st.column_config.ImageColumn("サムネイル", width="medium"),
            "サービス内容": st.column_config.TextColumn("サービス内容", width="large"),
            "購入にあたってのお願い": st.column_config.TextColumn(
                "購入にあたってのお願い", width="large"
            ),
            "よくある質問": st.column_config.TextColumn("よくある質問", width="large"),
        },
    )
    st.caption(
        "サムネイルはクリックで拡大表示できます。"
        "長い文章のセルはクリックすると全文が読めます（CSV/Excelには全文が入ります）。"
    )
    if not result.get("with_details"):
        st.info(
            "サービス内容は冒頭のみです。全文と、お気に入り数・オプション・よくある質問を"
            "取得するには、サイドバーの「詳細ページも取得する」を有効にして再実行してください。"
        )
    elif result.get("detail_limit", 0) < len(df):
        st.info(
            f"詳細情報は上位 {result['detail_limit']} 件のみ取得しています"
            f"（全 {len(df)} 件）。件数はサイドバーで変更できます。"
        )

# ---- テキストマイニング ----
with tab_mining:
    text_source = st.radio(
        "分析対象テキスト",
        ["タイトル＋キャッチコピー", "タイトルのみ", "サービス内容"],
        horizontal=True,
    )
    if text_source == "タイトルのみ":
        texts = df["タイトル"].fillna("").tolist()
    elif text_source == "サービス内容":
        if "サービス内容" not in df.columns:
            st.warning(
                "サービス内容の全文を分析するには、サイドバーの「詳細ページも取得する」を"
                "有効にして再実行してください。"
            )
            st.stop()
        texts = df["サービス内容"].fillna("").tolist()
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
PRICE_BINS = [0, 1000, 3000, 5000, 10000, 30000, 50000, 100000, float("inf")]
PRICE_LABELS = [
    "〜1千円", "1〜3千円", "3〜5千円", "5千〜1万円",
    "1〜3万円", "3〜5万円", "5〜10万円", "10万円〜",
]


def _band_chart(source: pd.DataFrame, value_col: str, y_title: str, color: str):
    """価格帯を横軸にした棒グラフ（縦軸は必ず0から始める）。"""
    base = alt.Chart(source).encode(
        x=alt.X(
            "価格帯:N",
            sort=PRICE_LABELS,
            axis=alt.Axis(labelAngle=0, title="価格帯", labelFontSize=11),
        )
    )
    bars = base.mark_bar(color=color, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        y=alt.Y(
            f"{value_col}:Q",
            title=y_title,
            scale=alt.Scale(domainMin=0, nice=True),
            axis=alt.Axis(tickMinStep=1),
        ),
        tooltip=[
            alt.Tooltip("価格帯:N"),
            alt.Tooltip("出品数:Q", title="出品数（件）"),
            alt.Tooltip("平均販売実績:Q", title="平均販売実績（件）", format=".1f"),
        ],
    )
    labels = base.mark_text(dy=-9, fontSize=11, color="#888").encode(
        y=alt.Y(f"{value_col}:Q"),
        text=alt.Text(f"{value_col}:Q", format=",.0f"),
    )
    return (bars + labels).properties(height=260)


with tab_price:
    if not price.notna().any():
        st.warning("価格データが取得できませんでした。")
    else:
        band = pd.cut(price, bins=PRICE_BINS, labels=PRICE_LABELS)
        agg = (
            pd.DataFrame({"価格帯": band, "販売実績": sold})
            .groupby("価格帯", observed=False)
            .agg(出品数=("販売実績", "size"), 平均販売実績=("販売実績", "mean"))
            .reindex(PRICE_LABELS)
            .fillna(0)
            .reset_index()
        )
        agg["平均販売実績"] = agg["平均販売実績"].round(1)

        st.subheader("① どの価格帯に競合が集中しているか")
        st.caption("価格帯ごとの出品数。棒が高いほどライバルが多い価格帯です。")
        st.altair_chart(
            _band_chart(agg, "出品数", "出品数（件）", "#4C78A8"),
            use_container_width=True,
        )

        st.subheader("② どの価格帯が売れているか")
        st.caption(
            "価格帯ごとの平均販売実績。①で出品数が少ないのに②で棒が高い価格帯は、"
            "ライバルが少ないのに売れている＝狙い目の価格帯です。"
        )
        st.altair_chart(
            _band_chart(agg, "平均販売実績", "平均販売実績（件）", "#54A24B"),
            use_container_width=True,
        )

        st.subheader("価格帯ごとのまとめ")
        summary = agg.copy()
        summary["出品数"] = summary["出品数"].astype(int)
        summary["構成比"] = (
            summary["出品数"] / max(summary["出品数"].sum(), 1) * 100
        ).round(1).astype(str) + "%"
        st.dataframe(
            summary[["価格帯", "出品数", "構成比", "平均販売実績"]],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.subheader("販売実績 TOP10")
    st.caption("このジャンルで最も売れている出品。価格設定と訴求の参考にしてください。")
    top_cols = [c for c in ["タイトル", "価格", "販売実績", "評価", "出品者", "サービスURL"] if c in df.columns]
    top_sold = df.nlargest(10, "販売実績")[top_cols]
    st.dataframe(
        top_sold,
        use_container_width=True,
        hide_index=True,
        column_config={
            "サービスURL": st.column_config.LinkColumn("サービスURL", display_text="開く"),
        },
    )

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

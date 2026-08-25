"""日本語テキストマイニング（janomeベース）。

以前はUserLocalのテキストマイニングサイトにCSVをアップロードしていたが、
Seleniumでのブラウザ自動化が必要で壊れやすいため、アプリ内で完結させる。
（UserLocalを使いたい場合のために、アップロード用CSVのダウンロードも用意）
"""

from __future__ import annotations

from collections import Counter

from janome.tokenizer import Tokenizer

_tokenizer: Tokenizer | None = None

# 頻度分析から除外する一般的すぎる語
STOPWORDS = {
    "する", "いる", "ある", "なる", "できる", "れる", "られる", "ます", "です",
    "こと", "もの", "ため", "よう", "さん", "方", "的", "等", "他", "中",
    "お", "ご", "御", "円", "件", "名", "個", "対応", "可能", "提供",
    "いたし", "致し", "致す", "いたす", "いただく", "頂く", "下さる",
    "下さい", "ください", "承り", "承ります", "出来る", "致します",
}

def _is_kanji(ch: str) -> bool:
    return "一" <= ch <= "鿿"

# 抽出対象の品詞（名詞・動詞・形容詞。ただし名詞の非自立・代名詞・数は除く）
_EXCLUDED_NOUN_SUBTYPES = {"非自立", "代名詞", "数", "接尾"}


def _get_tokenizer() -> Tokenizer:
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer()
    return _tokenizer


def extract_words(texts: list[str], pos_filter: set[str] | None = None) -> list[list[str]]:
    """テキストごとに、分析対象となる単語（基本形）のリストを返す。"""
    if pos_filter is None:
        pos_filter = {"名詞", "動詞", "形容詞"}
    tokenizer = _get_tokenizer()
    docs: list[list[str]] = []
    for text in texts:
        words: list[str] = []
        if not text:
            docs.append(words)
            continue
        for token in tokenizer.tokenize(str(text)):
            pos_parts = token.part_of_speech.split(",")
            pos = pos_parts[0]
            if pos not in pos_filter:
                continue
            if pos == "名詞" and pos_parts[1] in _EXCLUDED_NOUN_SUBTYPES:
                continue
            base = token.base_form if token.base_form != "*" else token.surface
            # 1文字の語は漢字のみ許可（"D" や "2" のような分割片を除外）
            if len(base) <= 1 and not _is_kanji(base):
                continue
            if base in STOPWORDS:
                continue
            words.append(base)
        docs.append(words)
    return docs


def word_frequency(docs: list[list[str]], top_n: int = 50) -> list[tuple[str, int]]:
    counter = Counter(w for doc in docs for w in doc)
    return counter.most_common(top_n)


def bigram_frequency(docs: list[list[str]], top_n: int = 30) -> list[tuple[str, int]]:
    """同一テキスト内で連続して出現した単語ペアの頻度。"""
    counter: Counter = Counter()
    for doc in docs:
        for a, b in zip(doc, doc[1:]):
            if a != b:
                counter[f"{a} × {b}"] += 1
    return counter.most_common(top_n)


def cooccurrence(docs: list[list[str]], top_n: int = 30) -> list[tuple[str, int]]:
    """同一テキスト（＝同一サービス）内に共起した単語ペアの頻度。"""
    counter: Counter = Counter()
    for doc in docs:
        uniq = sorted(set(doc))
        for i, a in enumerate(uniq):
            for b in uniq[i + 1:]:
                counter[f"{a} × {b}"] += 1
    return counter.most_common(top_n)


def build_wordcloud(freq: dict[str, int], font_path: str, width=900, height=500):
    from wordcloud import WordCloud

    wc = WordCloud(
        font_path=font_path,
        width=width,
        height=height,
        background_color="white",
        colormap="viridis",
        prefer_horizontal=0.9,
    )
    return wc.generate_from_frequencies(freq)

# ココナラ競合分析＋テキストマイニング（Webアプリ版）

旧Google Colabノートブックを、URLを共有するだけで誰でも使えるWebアプリ（Streamlit）として作り直したものです。

## 旧Colab版からの変更点

| | 旧Colab版 | 新Webアプリ版 |
|---|---|---|
| 共有方法 | ノートブックをコピーして各自実行 | URLを開くだけ |
| データ取得 | Selenium＋Chrome（重い・壊れやすい） | ページ埋め込みデータを直接取得（軽い・速い） |
| カテゴリ一覧 | コードにハードコード（陳腐化していた） | ココナラから毎日自動取得（常に最新） |
| 出力先 | Googleスプレッドシート（認証が必要） | 画面表示＋CSV/Excelダウンロード |
| テキストマイニング | UserLocalにSeleniumで自動アップロード | アプリ内で完結（UserLocal用CSVも出力可） |
| 所要時間 | 3〜5分 | 数秒〜（詳細取得ありでも1〜2分） |

### 技術メモ：なぜSeleniumが不要になったか

ココナラはNuxt.js(SSR)で作られており、検索結果・サービス詳細の全データが
HTML内の `window.__NUXT__` にJSONとして埋め込まれています。
本ツールはこれを `requests` + `quickjs` で直接パースするため、
HTMLのクラス名変更の影響を受けにくく、ブラウザ自動化も不要です。

## 機能

- キーワード検索 / カテゴリ検索（大カテゴリ・小カテゴリは自動で最新化）
- 並び順：おすすめ順・新着順・ランキング・お気に入り数順
- 1〜5ページ（最大約300件）取得
- オプションで詳細ページも取得（お気に入り数・本文・オプション・よくある質問・納期）
- サマリー指標（平均価格・中央値・平均販売実績）
- テキストマイニング：ワードクラウド・頻出単語・連続語ペア・共起語ペア
- 価格帯分布・販売実績TOP10・価格×実績の散布図
- CSV（UTF-8 / Shift-JIS）・Excelダウンロード、UserLocal用CSV出力

## ローカルでの実行

```bash
cd coconala-research-app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## 共有用に公開する（Streamlit Community Cloud・無料）

1. このフォルダ（coconala-research-app）をGitHubリポジトリにpushする（プライベートリポジトリでOK）
2. https://share.streamlit.io にGitHubアカウントでログイン
3. 「Create app」→ リポジトリと `app.py` のパスを指定してDeploy
4. 発行されたURL（`https://xxxx.streamlit.app`）を共有するだけ

- アプリを非公開にしたい場合：アプリ設定の「Sharing」で閲覧者のメールアドレスを指定できます（招待制）
- 一定期間アクセスがないとスリープしますが、誰かがURLを開けば自動で再起動します

### もしクラウド上でココナラへのアクセスがブロックされた場合

Streamlit Community Cloudは海外のクラウドIPのため、ココナラ側のbot対策で
ブロックされる可能性がゼロではありません。その場合の代替：

- Hugging Face Spaces（同じコードがそのまま動く・無料）
- 国内VPS（さくら等）+ `streamlit run`
- 各自のPCでローカル実行（上記コマンド）

## 注意事項

- スクレイピングはココナラのサーバーに負荷をかけないよう、リクエスト間隔を空けています。取得ページ数・詳細取得件数は必要最小限にしてください
- 取得したデータは競合リサーチの参考情報としての利用にとどめてください
- ココナラ側の仕様変更でデータ構造が変わると動かなくなる場合があります。エラーメッセージにその旨が表示されます

## ファイル構成

```
coconala-research-app/
├── app.py           # Streamlit UI本体
├── scraper.py       # ココナラのデータ取得・パース
├── mining.py        # 日本語テキストマイニング（janome）
├── requirements.txt
└── fonts/ipaexg.ttf # ワードクラウド用日本語フォント（IPAexゴシック）
```

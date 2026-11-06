# タスク：公開前の最後の仕上げ（導入の説明・ADR・小さな守り）

- ID：T-18
- Phase：4
- 関連要件：SR-10、SR-11、NFR-03、配布形式・コード署名の決定事項
- ブランチ名：`docs/publish-ready`

## 目的

v0.9.0 の下書きリリースを、別ユーザーで**ブラウザからダウンロード**して確かめた（2026-11-06）。結果をもとに、公開の前に次を行う。

1. README に、ダウンロードから起動までの手順（SHA-256 の確かめ方、SmartScreen の画面が出たときの対応）を書く
2. ADR 0004 の「ダウンロードしたファイルでの確認」の宿題を閉じる
3. 試用で見つかった2つの弱点を直す（日本語を表示できない出力先で止まる、Action のハッシュのずれ）

## 確認の結果（ADR と README に使う）

- 下書きのリリースから zip と `.sha256` をブラウザでダウンロードし、SHA-256 が一致した
- 展開した `stream-buddy.exe` を開くと、SmartScreen の画面が出た
  - 1 枚目：「Windows によって PC が保護されました」「Microsoft Defender SmartScreen は認識されないアプリの起動を停止しました」。ボタンは「実行しない」と「詳細情報」
  - 2 枚目（「詳細情報」を押したあと）：「アプリ：stream-buddy.exe」「発行元：不明な発行元」。ボタンは「実行」と「実行しない」
- 「実行」を押すと起動でき、Defender にブロックされなかった
- `--version` は `stream-buddy 0.9.0 (e17b827, 2026-11-05)`（GitHub Actions のビルド）
- 画面写真は人が `docs/images/smartscreen-1.png`・`docs/images/smartscreen-2.png` として置く（個人の情報は写っていない）

## 読む設計書

- `CLAUDE.md`
- `docs/adr/0004-exe-packaging.md`、`docs/build.md`、`README.md`
- `.github/workflows/ci.yml`、`.github/workflows/release.yml`（**読むだけ**。変更しない）
- `src/stream_buddy/__main__.py`

## 追加してよい依存

なし。

## 仕様

### 1. README「導入」の節

次の順で、初めての人が迷わないように書く。画面写真は `docs/images/` のものを使う。

1. **ダウンロード**：Releases から `stream-buddy-vX.Y.Z-windows-x64.zip` と `.sha256` の2つを落とす
2. **本物か確かめる**（任意だがおすすめ）：PowerShell で次の1行を実行し、「一致しました」と出ること
   ```powershell
   $name="stream-buddy-vX.Y.Z-windows-x64.zip"; $a=(Get-FileHash $name -Algorithm SHA256).Hash.ToLower(); $b=(Get-Content "$name.sha256" -Raw).Split(" ")[0].Trim(); if($a -eq $b){"一致しました：本物です"}else{"一致しません！ 使わないでください"}
   ```
   - さらに確かめたい人向けに、GitHub CLI の `gh attestation verify <zip> --repo Tsukimi-0919/stream-buddy` で、GitHub Actions でビルドされたことを確かめられると書く
3. **展開**：好きなフォルダに展開する（日本語を含むフォルダでもよい）
4. **音声認識モデル**：今の README の取得手順へのリンク
5. **起動と SmartScreen**：
   - 初めて開くと、画面写真の青い画面が出ることを、2 枚の画面写真とともに説明する
   - 出る理由：コード署名をしていないため（費用をかけない方針。ADR 0004）。悪いものだという意味ではないが、**上の SHA-256 の確認をした zip だけ**を実行すること
   - 「詳細情報」→「アプリ：stream-buddy.exe」であることを確かめて「実行」
   - **公式の Releases 以外から手に入れた exe は実行しない**
6. **OBS の設定**：今の README の説明へのリンク

`vX.Y.Z` はそのまま書く（バージョンごとに直さなくてよいように）。

### 2. ADR 0004

- 「ダウンロードしたファイルでの確認（Phase 4）」として、上の確認の結果を記録する
- 決定（onedir の zip、署名しない）は**変えない**。SmartScreen の警告は予想どおりで、README の説明で対応する、と書く
- 未決だった「ダウンロード時の SmartScreen と Defender の確認」を閉じる

### 3. 出力先が日本語を表示できなくても止まらない

- リリースのビルドで、日本語の出力が `UnicodeEncodeError` で止まった（Actions の Windows は英語環境のため）。配信者の PC でも、出力をファイルや別のプログラムに渡すと同じことが起きうる
- `__main__.py` の最初で、標準出力と標準エラーの `errors` を `"replace"` にする（`sys.stdout.reconfigure(errors="replace")` など）。表示できない文字は `?` などに置き換わり、**止まらない**
  - コンソールに直接表示する通常の使い方では、今までどおり日本語で表示される
- `scripts/build_exe.py` にも同じことを行う
- テスト：日本語を表示できない文字コード（例：`cp1252`）の出力先に、日本語のメッセージを出しても例外にならない

### 4. Action のハッシュがそろっているかのテスト

- Dependabot が `ci.yml` だけを更新し、`release.yml` の `setup-uv` が古いハッシュのまま残ったことがあった
- `tests/test_workflows.py` を作り、`.github/workflows/` のすべてのファイルを読んで確かめる
  - `uses:` はすべて **40 文字のコミットハッシュ**で書かれている（タグやブランチ名ではない）
  - **同じ Action** が複数の場所で使われていたら、ハッシュがすべて同じ
  - 違っていたら、どのファイルのどの Action かをメッセージで示す
- ワークフローのファイルは**読むだけ**。テストのために変更しない
- 今の時点でテストが失敗する場合は、**ワークフローを直さずに**、どこがずれているかを報告する（`.github/` は人が直す）

## テスト

- 上の 3 と 4 のテスト
- README の SHA-256 のコマンドに、`Get-FileHash` と `.sha256` が含まれている（文字列で確かめる）
- README から `docs/images/smartscreen-1.png` と `smartscreen-2.png` への参照がある

## やること

1. `docs/publish-ready` ブランチを **`origin/main` から**作る
2. 上の仕様を実装し、テストを書く
3. `docs/status.md` を更新する
4. 画面写真のファイルが `docs/images/` にまだないときは、置き場所とファイル名を報告に書く（人が置く）

## やらないこと

- `.github/` の変更（ずれがあれば報告のみ）
- バージョン番号の変更、タグ・リリースの操作
- コード署名

## 変更してよいファイル

- `README.md`
- `docs/adr/0004-exe-packaging.md`、`docs/build.md`（README の手順と食い違う場合のみ）、`docs/status.md`
- `docs/images/`（README から参照するだけ。画面写真は人が置く）
- `src/stream_buddy/__main__.py`、`scripts/build_exe.py`（出力の設定のみ）
- `tests/test_workflows.py`（新規）、`tests/` 配下（このタスクに関係するもの）
- `tasks/T-18-publish-docs.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `docs/publish-ready` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した

# exe のビルドと確認の手順（T-07 の試作）

stream-buddy を PyInstaller で exe にし、Python を入れていない PC でも動くかを確かめるための手順。
確認の結果は `docs/adr/0004-exe-packaging.md` に記録する。

## 1. ビルド

ビルドの設定はすべて `scripts/build_exe.py` にまとめてある（Nuitka に切り替えるときは、このファイルだけを直す）。

```
uv run --group build python scripts/build_exe.py --mode onedir
uv run --group build python scripts/build_exe.py --mode onefile
```

`--mode` を指定しないときは onedir になる（配布に使う形。ADR 0004）。

| モード | 出力の場所 | 中身 |
| --- | --- | --- |
| onedir | `dist/stream-buddy/` | `stream-buddy.exe`、`_internal/`（Python 本体とライブラリ）、`config.example.toml` |
| onefile | `dist/stream-buddy-onefile/` | `stream-buddy.exe`（1 ファイル）、`config.example.toml` |

- ビルドの前に、同じモードの前回の出力（`dist/` と `build/` の中の stream-buddy のフォルダ）だけを消す。もう一方のモードの出力は残る
- 終わると、出力の場所・サイズ（onedir はフォルダ全体、onefile は exe）・`stream-buddy.exe` の SHA-256 を表示する
- ビルドの前に、`git rev-parse --short HEAD` と `git status --porcelain` でコミットと変更の有無を調べ、
  ビルドの情報（`{"commit": "...", "dirty": false, "date": "YYYY-MM-DD"}`）を `build/build_info.json` に書く。
  exe の中には `stream_buddy/data/build_info.json` として同梱する（`src/` には書かない）
  - 日付はビルドした PC のローカルの日付
  - git が見つからない・失敗したとき（リポジトリの外など）は、ビルドしない（終了コード 1）
- ビルドした exe で `--version` を実行し、次の形が出なければ失敗（終了コード 1）とする（バージョンは `pyproject.toml` の `version`。例は 0.9.0）
  - コミットしてからビルドしたとき：`stream-buddy 0.9.0 (b12307a, 2026-11-05)`
  - コミットしていない変更（追跡していないファイルを含む）があるとき：`stream-buddy 0.9.0 (b12307a+dirty, 2026-11-05)`
  - 配る exe は、コミットしてから（`+dirty` が付かない状態で）ビルドする
- UPX による圧縮は使わない。音声認識のモデルとスパイクの依存、テストの依存（pytest・mypy）は含めない
- `dist/` と `build/` は `.gitignore` 済み

## 2. 動作確認

onedir と onefile のそれぞれで、`stream-buddy.exe` のあるフォルダで PowerShell を開いて行う。

1. `.\stream-buddy.exe --version` → `stream-buddy <バージョン> (<コミット>, <ビルドした日>)` と出る
   - ビルドしたときにコミットしていない変更があれば、コミットのあとに `+dirty` が付く
   - ソースから動かしたとき（`uv run stream-buddy --version`）は `stream-buddy <バージョン> (dev)`。ビルドの情報が壊れているときは `(unknown)`
2. `.\stream-buddy.exe --list-devices` → マイクの一覧が出る（PortAudio の DLL が読み込めている）
3. `.\stream-buddy.exe --demo` → OBS 用の URL が表示される
   - OBS のブラウザソースにその URL を設定し、メンダコが表示されて動く（口パク・吹き出しなど）
   - メンダコの絵や動きが出ないときは、ページの CSS・JS が読めていない。URL のパスを `/overlay?token=…` から `/static/style.css` に変えてブラウザで開き、中身が出るかを見る
   - Ctrl+C で終わる
4. `--demo` なしで起動 → 話すとメンダコが口パクする

### 設定ファイルの場所

- 設定ファイルは、起動したときのカレントフォルダの `config.toml`（なければ既定値）
- exe をエクスプローラーからダブルクリックしたときのカレントフォルダは、exe のあるフォルダ。
  onefile でも同じ（展開先の一時フォルダではない）
- そのため、exe の隣にある `config.example.toml` を `config.toml` にコピーして書き換えれば、ダブルクリックでもその設定で動く
- ショートカットから起動するときは、ショートカットの「作業フォルダー」がカレントフォルダになる

## 3. Python を使わずに動くかの確認

1. `dist/stream-buddy/`（onedir）と `dist/stream-buddy-onefile/`（onefile）を、フォルダごとリポジトリの外（例：デスクトップ）にコピーする
2. コピーした先の `stream-buddy.exe` をダブルクリックで起動し、URL が表示されることを確かめる
3. PowerShell からも、2 の動作確認（`--version`、`--list-devices`、`--demo`）を行う

できれば、Python を入れていない別の PC（または Windows サンドボックス）でも同じことを確かめる。

## 4. Windows Defender の確認

管理者の PowerShell で、onedir と onefile のそれぞれのコピー先のフォルダに対して行う。

```powershell
Start-MpScan -ScanType CustomScan -ScanPath "<exe のフォルダ>"
Get-MpThreatDetection
```

- `Get-MpThreatDetection` が何も出さなければ、検知なし。出たら、その内容（`ThreatID` と検知の名前、対象のファイル）を記録する
- スキャンの後に exe を起動し、ブロックされないこと（削除・隔離されない、起動できる）を確かめる
- 署名をしていないため、インターネットから取得した exe では SmartScreen の警告が出る。この試作のビルドはローカルで作ったものなので、ここでは確認の対象外

## 5. 記録すること

onedir と onefile のそれぞれについて、次を `docs/adr/0004-exe-packaging.md` の表に記録する。

| 項目 | 測り方 |
| --- | --- |
| サイズ | ビルドの最後の表示（onedir はフォルダ全体、onefile は exe） |
| SHA-256 | ビルドの最後の表示 |
| 起動から URL 表示までの時間 | ダブルクリックしてから、コンソールに URL が表示されるまでをストップウォッチで測る（2〜3 回の平均）。onefile は初回と 2 回目以降で差が出ることがある |
| Defender の結果 | 手動スキャンの結果（検知なし／検知名）と、スキャン後に起動できたか |

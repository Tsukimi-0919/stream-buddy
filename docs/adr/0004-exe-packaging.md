# ADR 0004：exe の形（onedir と onefile）

- 状態：採用
- 日付：2026-10-26

## 背景

stream-buddy は PyInstaller で作る exe として配る（requirements.md の決定事項「配布形式」）。
PyInstaller には、フォルダで配る **onedir** と、1 ファイルで配る **onefile** の2つの形がある。

- onedir：`stream-buddy.exe` と `_internal/`（Python 本体とライブラリ）をフォルダごと配る
- onefile：`stream-buddy.exe` 1 つ。起動のたびに一時フォルダへ展開してから動く

署名しない exe は、Windows Defender に誤検知されることがある。どちらの形が誤検知されにくく、使いやすいかを比べて決める。

満たすべき要件と方針

- SR-11（配布物の改ざん）：GitHub Actions でビルドし、ビルド証明（artifact attestation）と SHA-256 を添える
- NFR-06（オフライン動作）：Python を入れていない PC でも、ネットワークなしで動く
- UPX による圧縮は使わない（誤検知が増えやすいため）

## 決定済みのこと

- **コード署名はしない**（requirements.md の決定事項「コード署名」）。そのため、ダウンロードした exe を初めて起動すると、
  SmartScreen の警告（「Windows によって PC が保護されました」）が出る
- README に、この警告が出る理由（署名していないこと）と、SHA-256 とビルド証明で配布物を確かめる方法を書く

## 比較の方法

- 道具：`scripts/build_exe.py`（手順は `docs/build.md`）
- 同じソースから onedir と onefile をビルドし、Python を入れていない状態（リポジトリの外にコピーした exe）で動かす
- 確認した環境
  - OS：Microsoft Windows 11 Home（10.0.26300）
  - CPU：12th Gen Intel Core i5-12400
  - メモリ：約 32 GB（34,111,909,888 バイト）
  - Defender の定義のバージョン：（記録なし）

## 比較の観点

| 観点 | 見るもの | 重み |
| --- | --- | --- |
| Defender の結果 | 手動スキャンで検知されないか。スキャン後に起動でき、ブロックされないか | 高 |
| 起動時間 | 起動してから OBS 用の URL が表示されるまでの時間 | 中 |
| サイズ | onedir はフォルダ全体、onefile は exe のサイズ | 低 |
| 配りやすさ | 利用者がダウンロードして展開・起動するまでの手間、SHA-256 の確かめやすさ、更新のしやすさ | 中 |

## 確認結果

`docs/build.md` の手順で、人間が確認した（2026-10-26）。onedir と onefile の両方を、リポジトリの外のフォルダにコピーして起動した。

| 形 | サイズ | `stream-buddy.exe` の SHA-256 | 起動から URL 表示まで | Defender の手動スキャン後の起動 |
| --- | --- | --- | --- | --- |
| onedir | 67.2 MB（フォルダ全体） | `82380281593b2441ca63d08c31887da59eb2250bbe06414c408b2cd27510fbaa` | 計測していない（体感で onedir がわずかに遅いが、気にならない程度） | ブロックされずに起動できた |
| onefile | 28.3 MB（exe） | `5f377742895f355e0f772c5141790b3f5d59e0c7eb8f711db6cdda15241e3ffc` | 計測していない | ブロックされずに起動できた |

- どちらも `--list-devices`、`--demo` での OBS の表示、`--demo` なしでの口パクが動いた
- SHA-256 は、確認に使ったビルド（T-07 の作業で最後にビルドしたもの）の値

## 決定

- **onedir を採用し、フォルダを zip にして配布する**
- 理由
  - 起動の速さの差は気にならない程度だったため、決め手にならない
  - 1 ファイル形式は、起動時に一時フォルダへ展開する動きが誤検知されやすいとされる。そのため onedir を選ぶ
- `scripts/build_exe.py` の既定のモード（`--mode` を指定しないとき）を onedir にする

### 注意

- 今回の Defender の確認は、自分の PC でビルドしたファイルに対するもの
- ダウンロードしたファイル（Mark of the Web 付き）での SmartScreen と Defender の確認は、
  Phase 4 で GitHub Actions のビルドを Releases に置いたときに行い、必要ならこの決定を見直す

## 結果

課題

- 使わない PortAudio の DLL（32bit・arm64・ASIO 版・macOS 用。約 2 MB）が含まれる。
  sounddevice 用の PyInstaller の設定（pyinstaller-hooks-contrib）がまとめて含めるため。誤検知が出る場合は Phase 4 で除外する
- 最初のビルドで mypy・pytest が exe に入り込んでいたため、ビルドスクリプトで除外した。
  依存を追加したときは、exe に入るものを確認する
- PyInstaller のビルドは毎回 SHA-256 が変わる。配布物の正しさは、CI でのビルドと attestation で保証する（SR-11）

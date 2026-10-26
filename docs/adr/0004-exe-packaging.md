# ADR 0004：exe の形（onedir と onefile）

- 状態：提案中
- 日付：（確認後に記入）

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
- 確認した環境：（Windows のバージョン、Defender の定義のバージョン、CPU を記入）

## 比較の観点

| 観点 | 見るもの | 重み |
| --- | --- | --- |
| Defender の結果 | 手動スキャンで検知されないか。スキャン後に起動でき、ブロックされないか | 高 |
| 起動時間 | 起動してから OBS 用の URL が表示されるまでの時間 | 中 |
| サイズ | onedir はフォルダ全体、onefile は exe のサイズ | 低 |
| 配りやすさ | 利用者がダウンロードして展開・起動するまでの手間、SHA-256 の確かめやすさ、更新のしやすさ | 中 |

## 確認結果

（`docs/build.md` の手順で確認して記入する）

| 形 | サイズ | `stream-buddy.exe` の SHA-256 | 起動から URL 表示まで | Defender の手動スキャン | スキャン後の起動 |
| --- | --- | --- | --- | --- | --- |
| onedir |  |  |  |  |  |
| onefile |  |  |  |  |  |

### 気づいたこと

- （確認で気づいたことを記入する）

## 決定

（確認後に記入）

## 結果

（採用した形を GitHub Actions でのビルドとリリースに反映する別の作業、README に書くことなどを記入）

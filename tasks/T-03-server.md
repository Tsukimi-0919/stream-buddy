# タスク：ローカルサーバー（ページ配信と WebSocket）

- ID：T-03
- Phase：1
- 関連要件：FR-03、SR-01、SR-02、SR-03、SR-04
- ブランチ名：`feat/server`

## 目的

OBS のブラウザソースが読み込むページを配信し、そのページとだけ WebSocket で通信できるサーバーを作る。
このプロジェクトで最も重要な守りの境界なので、**機能より先に守りを作り、守りをテストで証明する**。

## 読む設計書

- `CLAUDE.md`
- `docs/ws-protocol.md`（このタスクで確定させる）
- `docs/threat-model.md`（特に「信頼の境界」と SR-01〜SR-04）
- `docs/architecture.md`（`server` の責務、起動の流れ）
- `src/stream_buddy/config.py`

## 追加してよい依存

- 実行時：`fastapi`、`uvicorn`、`websockets`
  - `uvicorn[standard]` は使わない（不要な依存が増えるため）
- 開発用：`httpx`（FastAPI の TestClient に必要）
- これ以外は追加しない

## 仕様

### 待ち受け（SR-01）

- 待ち受けアドレスは **コード内の定数 `HOST = "127.0.0.1"`** とし、設定や引数で変えられないようにする
- ポートは設定の `server.port` を使う

### トークン（SR-02）

- 起動ごとに `secrets.token_urlsafe(32)` で作る。ファイルやログには保存しない
- 比較は `secrets.compare_digest` を使う

### Host ヘッダーの確認（DNS リバインディング対策）

- すべての HTTP リクエストと WebSocket 接続で、`Host` ヘッダーが `127.0.0.1:<port>` と一致しなければ `400` を返す
- 悪意あるサイトが DNS を書き換えて `127.0.0.1` を指させる攻撃（DNS リバインディング）を防ぐため

### ページ配信

- `GET /overlay?token=<token>`：トークンが正しければ `overlay/index.html` を返す。違えば `404`（存在を知らせない）
- `GET /static/...`：ページ用の CSS・JS・画像。トークン不要（秘密情報を含まないため）
- ページは `src/stream_buddy/overlay/` に置く。このタスクでは「stream-buddy」と表示するだけの仮のページでよい（本番のページは T-04）
- 上記以外のパスは `404`。FastAPI の `/docs`、`/redoc`、`/openapi.json` は**無効にする**

### すべての HTTP 応答に付けるヘッダー（SR-04）

- `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src ws://127.0.0.1:<port>; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`（URL のトークンを他へ渡さないため）
- `Cache-Control: no-store`

### WebSocket（SR-02、SR-03）

- `GET /ws?token=<token>` で接続する
- 接続を受け入れる前に、次をすべて確認する。どれかが違えば理由を伝えずに拒否する（`accept` しない）
  - トークンが一致する
  - `Origin` ヘッダーが `http://127.0.0.1:<port>` と完全一致する（`Origin` がない場合も拒否）
  - 同時接続数が 2 未満
- 受信メッセージの上限は 4 KB。超えたら接続を閉じる
- 受信メッセージは pydantic で検証し、`ws-protocol.md` の `hello` 以外、または形が違うものは**捨てて**ログに理由だけ残す（中身はログに残さない）。接続は切らない
- 送信用に `broadcast(message)` を用意する。引数は pydantic のモデルで、`ws-protocol.md` のサーバー→ページのメッセージだけを受け付ける
  - `say.text` は 1〜80 文字。超える場合はモデルの検証で弾く

### 起動

- `stream-buddy`（引数なし）でサーバーを起動する
- `--config <path>` で設定ファイルを指定できる。省略時はカレントフォルダの `config.toml`（なければ既定値）
- 起動したら、OBS に設定する URL（トークン入り）を**コンソールに1回だけ**表示する。あわせて「この URL を配信画面に映さないでください」と表示する
- 設定エラー（`ConfigError`）はメッセージを表示して終了コード 2 で終わる

## やること

1. `feat/server` ブランチを作る
2. 依存を追加する
3. `src/stream_buddy/protocol.py`：`ws-protocol.md` のメッセージを pydantic モデルにする（`extra="forbid"`）
4. `src/stream_buddy/server.py`：上記の仕様どおりに作る。アプリは `create_app(config, token)` で作れるようにし、テストから使えるようにする
5. `src/stream_buddy/overlay/index.html`：仮のページ（インラインのスクリプトやスタイルは書かない）
6. `src/stream_buddy/__main__.py`：起動処理を追加する（`--version` は残す）
7. テストを書く（`tests/test_protocol.py`、`tests/test_server.py`）。最低限、次を確認する
   - `HOST` が `"127.0.0.1"` であり、起動処理が uvicorn にそれを渡している
   - `/overlay`：正しいトークンで 200、トークンなし・違うトークンで 404
   - 違う `Host` ヘッダーで 400（HTTP と WebSocket の両方）
   - すべての応答に CSP など4つのヘッダーが付いている
   - `/docs`、`/openapi.json` が 404
   - WebSocket：トークンなし、違うトークン、`Origin` なし、違う `Origin` がすべて拒否される
   - WebSocket：正しい条件で接続でき、`hello` を送っても切れない
   - WebSocket：3本目の接続が拒否される
   - WebSocket：知らない `type`、余分なキー、壊れた JSON を送っても接続が切れず、その後の `broadcast` を受け取れる
   - WebSocket：4 KB を超えるメッセージで接続が閉じる
   - `broadcast` で送ったメッセージが、`ws-protocol.md` の形の JSON で届く
   - 81 文字の `say` は作れない
8. `docs/ws-protocol.md` を確定版にする（「草案」の表記を外し、ポートは設定の `server.port` に決まったことを書き、未決の欄を更新する）
9. `docs/threat-model.md` に DNS リバインディングと、その対策（Host ヘッダーの確認）を追記する
10. `docs/status.md` を更新する

## やらないこと

- 音声、ホットキー、テンション管理など、`server` 以外の機能
- 本番のページのデザインやメンダコの表示（T-04）
- 再接続の処理（ページ側の仕事。T-04）
- HTTPS 化（PC 内の通信のみのため不要）

## 変更してよいファイル

- `pyproject.toml`、`uv.lock`（上記の依存の追加のみ）
- `src/stream_buddy/protocol.py`、`src/stream_buddy/server.py`（新規）
- `src/stream_buddy/overlay/index.html`（新規）
- `src/stream_buddy/__main__.py`
- `tests/test_protocol.py`、`tests/test_server.py`（新規）、`tests/test_version.py`（起動処理の変更で必要な場合のみ）
- `docs/ws-protocol.md`、`docs/threat-model.md`、`docs/status.md`
- `tasks/T-03-server.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `uv sync --locked` が通る
- [ ] `uv run stream-buddy` で起動し、表示された URL をブラウザで開くと仮のページが出る（手動確認の手順を報告に書く）
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/server` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した

# 実装状況

> これは「今の姿」。目指す姿は [architecture.md](architecture.md) を参照。
> AI エージェントはタスク完了のたびにこのファイルを更新する。

## 現在のフェーズ

**Phase 2：実装中（T-08 の状態機械、T-09 のセリフ集を実装。入力・組み立ては未実装）**

Phase 0（設計と守りの準備）は完了。

## できていること

- リポジトリの守り（pre-commit、Claude Code の禁止設定、CI、Dependabot）
- 設計書の初版（requirements / architecture / threat-model / ws-protocol）
- T-01：プロジェクトの土台（uv、`src/` レイアウト、Python 3.12 固定、ruff / mypy / pytest の設定）
  - `stream-buddy --version` でバージョンを表示できる
- T-02：設定ファイルの読み込みと検証（`src/stream_buddy/config.py`）
  - `load_config(path)` が TOML を読み、型と範囲を検証した変更不可の `Config` を返す。ファイルがなければ既定値
  - 知らないキー・範囲外の値・F1〜F12 以外のホットキー・death と clear の重複・`log.enabled = true` で `output_dir` が空／相対パス・壊れた TOML は、日本語メッセージの `ConfigError` になる
  - host は設定に含めない（SR-01）。`log.output_dir` はエラーメッセージに値を出さない
  - 設定例は `config.example.toml`
- T-03：ローカルサーバー（`src/stream_buddy/server.py`、`src/stream_buddy/protocol.py`）
  - 実行時の依存：pydantic、fastapi、uvicorn（`[standard]` なし）、websockets。開発用に httpx
  - `stream-buddy [--config <path>]` で起動。省略時はカレントフォルダの `config.toml`（なければ既定値）。設定エラーは終了コード 2
  - 起動時にトークン入りの OBS 用 URL をコンソールに1回だけ表示し、配信画面に映さないよう注意を出す
  - `127.0.0.1` 固定で待ち受け（定数 `HOST`）。`Host` ヘッダーが `127.0.0.1:<port>` 以外なら拒否（HTTP は 400、WebSocket は accept せずに閉じる）
  - `/overlay?token=` は正しいトークンのときだけページ（`overlay/index.html`）を返し、それ以外は 404。`/docs` などは無効
  - `/static/` は `overlay/static/` フォルダがあるときだけ配信する
  - すべての HTTP 応答に CSP・`X-Content-Type-Options`・`Referrer-Policy`・`Cache-Control` を付ける
  - WebSocket は トークン・Origin・同時接続 2 本まで を確認してから受け入れる。受信は `hello` だけを受け付け、それ以外は破棄してエラーの種類だけをログに残す。4 KB 超で close 1009
  - `Hub.broadcast` でサーバー → ページのメッセージを送る
  - URL のトークンが出ないよう、uvicorn のアクセスログと info ログは止めている。FastAPI 組み込みの OpenTelemetry も止めている
  - `docs/ws-protocol.md` を確定版にした（JSON Schema ファイルは置かず、仕様と `protocol.py` の一致はテストで確認する）。`docs/threat-model.md` に DNS リバインディングを追記した

- T-04：OBS 用のページ（`overlay/index.html`、`overlay/static/style.css`、`overlay/static/app.js`）
  - 仮のメンダコをオリジナルの SVG で描画（丸い体、ひれ、目、閉じた口と開いた口）
  - WebSocket で接続し `hello` を送る。切れたら 1 秒から倍々、上限 10 秒で再接続し、つながったら 1 秒に戻す
  - 受信メッセージは形を厳密に確認し、合わないものは無視。`speech`（口パク）、`tension`（calm / normal / high のアニメーション）、`say`（吹き出しを 5 秒表示）、`display`（透過 / 緑）を表示する。`effect` は受け取るだけ
  - 文字は `textContent` のみ。インラインのスクリプト・スタイル・`console` は使わない（テストで検査）
  - サーバーは `hello` を受け取ると、そのページにだけ設定の `display.background` を送る
  - `stream-buddy --demo` で、決まった流れ（`src/stream_buddy/demo.py`）を 2.5 秒間隔で繰り返し送る
  - Windows のレジストリの設定に左右されないよう、`.js` と `.css` の Content-Type を明示した
  - トークンを保存して使い回すようにした（ADR 0002、`src/stream_buddy/token_store.py`）
    - 初回に作って `%LOCALAPPDATA%\stream-buddy\token` に保存し、2回目以降は読み込む。形が違えば作り直す。書き込みは一時ファイル経由で置き換え
    - `--reset-token` で作り直し、OBS の URL の設定し直しを案内する。`LOCALAPPDATA` がなければ終了コード 2
    - stream-buddy を再起動しても URL が変わらず、ページは自動で再接続する
    - テストは `tests/conftest.py` で `LOCALAPPDATA` を一時フォルダに差し替え、実際の場所には書かない
- T-05：マイク入力と発話検知（`src/stream_buddy/audio.py`、`src/stream_buddy/detect.py`）
  - 実行時の依存に sounddevice、numpy を追加
  - モノラル・16 kHz・480 サンプル（約 30 ms）のブロックで入力し、コールバックの中で音量（dBFS、無音は -100.0）だけを計算する。サンプルは持ち出さない・ためない・ファイルに書かない
  - マイクは設定の `audio.device` が空なら OS の既定、空でなければ名前にその文字列を含む最初の入力デバイス。見つからなければ一覧を添えて終了コード 2
  - 発話検知はしきい値（`audio.speech_threshold_db`）を超えるブロックが 2 回続いたら話し始め、しきい値以下が 300 ms（10 ブロック）続いたら話し終わり。変化したときだけ `speech` を送る
  - 音声のスレッドからは `call_soon_threadsafe` で音量だけをループに渡し、1 本のタスクが順番どおりに `broadcast` する
  - `--list-devices` で入力デバイスの番号・名前・ホスト API を表示する。`--demo` のときはマイクを開かない。終了時（Ctrl+C を含む）にストリームを閉じる
  - テストでは sounddevice の代わりに偽のバックエンドを使う（`tests/conftest.py`）。本物のマイクがない CI でも通る
- T-06：音声認識エンジンの比較の道具（スパイク。本体は変更なし）
  - `spikes/asr_compare.py` と `spikes/README.md`。Vosk と faster-whisper（tiny・base）に同じ発話をかけ、正解率・誤検知・処理時間・CPU 時間・モデルのサイズと SHA-256 を Markdown の表で出す
  - 依存は `spike-asr` グループに分けた（本体・dev・CI・exe には入らない）
  - マイクを開かない `--self-test`（無音とノイズ）で、faster-whisper の取得・読み込み・実行を確認した。Vosk はモデルがないときに手動取得の手順を出して終わることを確認した（モデルを使った実行は未確認）
  - `docs/adr/0003-asr-engine.md` に 3 回の測定結果と決定を記録した（状態：採用）
  - 1回目の測定で Vosk を第一候補にした。課題（「死んだ」「勝った」が語彙にない、「クリーム」を「クリア」と誤検知）を確かめるため、比較スクリプトを直した
    - Vosk の文法を「死ん だ」「勝っ た」のように語彙にある単語の句にした
    - Vosk の文法におとりの言葉（クリーム、しんどい、かったるい、買った、よかった）を入れ、おとりとして認識されたら「検知なし」とする
    - 2回目の測定に向けて、読み上げる「キーワードではない言葉」に「買った」「よかった」「わかった」「なんだ」を加えた。「わかった」「なんだ」は、おとりで防げない似た音の誤検知を測るため、おとりの言葉に入れていない
    - `--engines vosk --self-test` で、語彙にない単語がなく、Vosk がエラーなく動くことを確認した
  - 2回目の測定で、エンジンは Vosk を採用した。「勝った」は「買った」と同じ音で区別できないため、クリアの既定のキーワードから外す方針にした（ADR 0003）
    - 3回目の測定に向けて、キーワードを「死んだ」「やられた」「クリア」「やったー」「ナイス」、読み上げる「キーワードではない言葉」を「わかった」「やっぱり」「ないです」「買った」「なんだ」「クリーム」、おとりの言葉を「クリーム」「しんどい」「かったるい」にした
  - 3回目の測定で、既定のキーワードを死亡「死んだ」「やられた」、クリア「クリア」「やったー」に決めた。「ナイス」は「ないです」とほぼ同じ音のため外した。既定のおとりの言葉は「やっぱり」「クリーム」「しんどい」「かったるい」（ADR 0003）
- T-07：PyInstaller での exe 化の試作（本体は変更なし）
  - `scripts/build_exe.py` に PyInstaller の設定をまとめた。`--mode onedir` / `--mode onefile` でビルドし、サイズと `stream-buddy.exe` の SHA-256 を表示し、`--version` が `0.1.0` になるかを確かめる（違えば終了コード 1）
  - 依存は `build` グループに分けた（pyinstaller。本体・dev には入らない）
  - 出力は onedir が `dist/stream-buddy/`、onefile が `dist/stream-buddy-onefile/`。どちらも exe の隣に `config.example.toml` を置く。コンソールは表示し、UPX は使わない
  - OBS 用のページは exe の中の `stream_buddy/overlay` に置き、`server.py` の `Path(__file__).parent / "overlay"` のまま見つけられるようにした。PortAudio の DLL は `_sounddevice_data/portaudio-binaries` に入る
  - 音声認識のスパイクの依存と、テスト・型チェックの依存（pytest・mypy）は含めない
  - onedir と onefile の両方でビルドでき、`--version` で `0.1.0` が出ることを確認した
  - 人間が `docs/build.md` の手順で確認した。どちらもリポジトリの外で `--list-devices`・`--demo` での OBS の表示・口パクが動き、Defender の手動スキャンの後もブロックされずに起動できた
  - onedir を採用し、フォルダを zip にして配布する（ADR 0004、状態：採用）。`scripts/build_exe.py` の既定のモードを onedir にした
  - 課題（ADR 0004）：ダウンロードしたファイル（Mark of the Web 付き）での SmartScreen と Defender の確認は Phase 4。使わない PortAudio の DLL（約 2 MB）が含まれる。依存を追加したときは exe に入るものを確認する

- T-08：状態機械（`src/stream_buddy/state/`。docs/state-machine.md の v1 に従う）
  - テンション（ST-01〜ST-04）、沈黙ハンター（ST-11〜ST-15）、イベント（ST-21〜ST-25）、出口（Arbiter）と、4 つをまとめる `Brain`
  - 各状態機械は `step(入力, now_ms)` を持つクラス。時刻は引数で受け取り、`time`・`random`・`asyncio`・`sounddevice`・`fastapi` を import しない（テストで検査）
  - 数値は `state/constants.py` に集めた。沈黙の秒数だけは `Brain` の引数で渡す（設定の `silence.seconds` を渡す想定）
  - `tests/state/` に遷移の ID ごとのテスト、境界のテスト、`Brain` を通したシナリオテスト。state-machine.md のすべての `ST-xx` がテスト名に出ることもテストで確かめる
  - まだどこからも使っていない（サーバー・音声・`--demo` との組み立ては T-12）

- T-09：セリフ集の読み込みと選択（`src/stream_buddy/lines.py`）
  - 既定のセリフ集は `src/stream_buddy/data/lines.toml`（人間が書いたもの。文言は変えない）。`importlib.resources` で読み、exe にも同梱する
  - 6 つのリスト（`[silence]` の calm / normal / high、`[tension]` の high、`[event]` の death / clear）はすべて必須。各 1〜30 個、各セリフ 1〜80 文字。空白だけ・改行・タブ・制御文字は不可（絵文字のゼロ幅接合子と異体字セレクタは可）
  - エラーは `LinesError`（`ConfigError` の一種）。どのセリフかは何番目かで示し、セリフの本文とファイルのパスは出さない
  - 設定の `[lines] file` で自分のセリフ集に差し替えられる。空文字なら既定、絶対パスのみ、64 KB まで。読めない・誤りがあるときは既定に戻さずエラー
  - `LinePicker.pick(場面, テンション)` が `(line_id, text)` を返す。`line_id` は「表.キー.番号」（番号は 1 から）。同じリストの直前のセリフは選ばない。乱数は外から渡せる
  - まだどこからも使っていない（出口のあとにつなぐのは T-12）

## まだないもの

- 機能モジュール（hotkey / log）
- 状態機械とサーバー・音声の組み立て（T-12）
- キーワード検知の本体への組み込み（エンジンは Vosk に決定済み）
- CPU 使用率の計測（NFR-01）
- 死亡・クリアの演出（Phase 3）
- メンダコの本番の画像（今は仮の SVG）
- ログ出力先フォルダの存在確認・書き込み時のパス確認（ログのタスクで行う）

## 次にやること

- T-10：キーワード検知の本体への組み込み（既定のキーワードとおとりの変更、`config.py`・`config.example.toml`・`requirements.md` の FR-07 の修正を含む）
- T-11：ホットキー（`RegisterHotKey`）
- T-12：組み立て（入力 → 状態機械 → WebSocket。`--demo` を状態機械経由に置き換え）

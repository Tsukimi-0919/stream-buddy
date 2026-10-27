# 実装状況

> これは「今の姿」。目指す姿は [architecture.md](architecture.md) を参照。
> AI エージェントはタスク完了のたびにこのファイルを更新する。

## 現在のフェーズ

**Phase 2：T-13 の反応の調整まで実装。手動確認（`--test-keywords` と OBS）待ち**

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
  - サーバーは `hello` を受け取ると、そのページにだけ設定の `display.background` と今のテンションを送る（テンションは T-12 から）
  - `stream-buddy --demo` で、デモの流れを繰り返し送る（T-12 から、偽の入力を状態機械に入れる形に変えた）
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
  - 発話検知はしきい値（`audio.speech_threshold_db`）を超えるブロックが 2 回続いたら話し始め、しきい値以下が 300 ms（10 ブロック）続いたら話し終わり。変化したときだけ `SpeechStarted` / `SpeechEnded` を状態機械に入れ、`speech` は状態機械の出力から送る（T-12 から）
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
  - T-12 で `app.py` からつないだ

- T-09：セリフ集の読み込みと選択（`src/stream_buddy/lines.py`）
  - 既定のセリフ集は `src/stream_buddy/data/lines.toml`（人間が書いたもの。文言は変えない）。`importlib.resources` で読み、exe にも同梱する
  - 6 つのリスト（`[silence]` の calm / normal / high、`[tension]` の high、`[event]` の death / clear）はすべて必須。各 1〜30 個、各セリフ 1〜80 文字。空白だけ・改行・タブ・制御文字は不可（絵文字のゼロ幅接合子と異体字セレクタは可）
  - エラーは `LinesError`（`ConfigError` の一種）。どのセリフかは何番目かで示し、セリフの本文とファイルのパスは出さない
  - 設定の `[lines] file` で自分のセリフ集に差し替えられる。空文字なら既定、絶対パスのみ、64 KB まで。読めない・誤りがあるときは既定に戻さずエラー
  - 設定ファイルとセリフ集は、BOM 付きの UTF-8 も読める（先頭の BOM だけを取り除く。セリフの中の U+FEFF は制御文字としてエラー）
  - `LinePicker.pick(場面, テンション)` が `(line_id, text)` を返す。`line_id` は「表.キー.番号」（番号は 1 から）。同じリストの直前のセリフは選ばない。乱数は外から渡せる
  - T-12 で、出口のあとの `Say` に使うようにした

- T-10：キーワード検知（`src/stream_buddy/keywords.py`。ADR 0003 の Vosk）
  - `vosk` を本体の依存に移した（`spike-asr` には `faster-whisper` だけが残る）。`vosk` は `requests`・`tqdm`・`srt` なども連れてくる
  - モデルの全 16 ファイルの SHA-256 の一覧を `src/stream_buddy/data/vosk-model-small-ja-0.22.sha256` に置いた（ADR 0003 の 5 ファイルと一致を確認）。読み込む前に照合し、ファイルがない・違う・余分があれば起動しない（SR-07）。`--check-model` で照合だけを行える
  - モデルのフォルダがなければ、キーワード検知なしで起動し、その旨を表示する。`[keywords] enabled = false` ならモデルを探さない
  - キーワードとおとりは、語彙にあればそのまま、なければ語彙の単語の最長一致で句にする（例：「死んだ」→「死ん だ」）。表せない言葉はエラー
  - 判定：おとりが含まれれば検知なし。キーワードが 1 種類だけ含まれれば `death` / `clear`。2 種類なら検知なし
  - 音声は `audio.BlockQueue`（最大 1 秒分、いっぱいなら捨てる）で認識用のスレッドに渡す。認識した文字列は判定したら捨て、どこにも出さない
  - Vosk は日本語などを含むパスのモデルを開けないため、読み込む間だけカレントフォルダをモデルのフォルダにして相対パスで渡す
  - `--test-keywords`：サーバーを起動せず、聞き取ったキーワードの種類だけを表示する。通常の起動では、T-12 から `Brain` につないでいる
  - 設定：`[keywords]` に `enabled`・`model_dir`・`decoys` を追加し、既定のキーワードを ADR 0003 の決定にした（clear から「勝った」を外した）
  - exe に Vosk の DLL とハッシュの一覧を同梱する（モデル本体は同梱しない）。exe で `--check-model` が動くことを確認した
  - 人間の手動確認（`uv run` と exe の両方）：`--check-model` が通り、`--test-keywords` で「死んだ」「やられた」→ death、「クリア」「やったー」→ clear、「クリーム」「しんどい」「わかった」「なんだ」→ 検知なし。exe の中で Vosk の DLL が読み込めた。「やっぱり」は 10 回中 0 回の誤検知で、おとりの効果を確認した（ADR 0003 の「決定」）。「かったるい」と改ざんの検知は手動では未確認（改ざんの検知は自動テストで確認済み）

- T-11：ホットキー（`src/stream_buddy/hotkey.py`）
  - 専用のスレッドで `RegisterHotKey(NULL, id, 修飾キー | MOD_NOREPEAT, VK_F1〜F12)` で 2 つのキーを登録し、`GetMessageW` で `WM_HOTKEY` を待つ。止めるときは `PostThreadMessageW(WM_QUIT)` を送り、`UnregisterHotKey` で必ず登録を外す（例外のときも）
  - Win32 API は標準ライブラリの `ctypes` で呼ぶ（`argtypes`・`restype` を設定、`use_last_error=True`）。`User32Api` に分け、テストでは偽物に差し替える
  - 登録に失敗したキーは無効にして続け、どのキーかを表示する（ほかのアプリが使っているときは、その旨と設定の変え方）
  - 設定の `[hotkeys]` に `[Ctrl+][Alt+][Shift+]F1〜F12` の組み合わせを書ける。順番・大文字小文字は問わず、正規の書き方（例：`Ctrl+Shift+F9`）にそろえて持つ。Win キー、F1〜F12 以外、修飾キーの重複、death と clear が同じ組み合わせはエラー
  - SR-05：キーボードのフック、キーの状態を調べる API、生の入力、キーボード関係のライブラリを `src/stream_buddy/` 全体で使わない（テストで検査）。`hotkey.py` が呼ぶ `user32` の関数は 4 つだけ（テストで検査）
  - `--test-hotkeys`：ホットキーだけを登録し、押されたキーの種類を表示する。通常の起動では T-12 から登録して `Brain` につなぐ。`--demo` では登録しない
  - 本物の Win32 API で、登録・ほかのアプリと重なったときの表示・`WM_QUIT` での停止と登録の解除を確認した（普段使わない組み合わせで。キーを押す確認は人間が行う）

- T-12：組み立て（`src/stream_buddy/app.py`）
  - `Engine`：すべての入力（発話・キーワード・ホットキー・100 ms ごとの `Tick`）を `asyncio` の 1 つのキュー（上限 1000、あふれたら捨てて数だけを警告）に集め、1 つのタスクだけが取り出して `Brain.step` に通す。時刻は取り出したときの `time.monotonic()`（差し替えられる）
  - 出力を `speech`・`tension`・`say`（`LinePicker` で今のテンションに合わせて選ぶ）・`effect` にして送る。`TensionPeak` は送らない（Phase 3 のログ用）
  - `Runtime`：サーバーの起動後に、マイク・認識用のスレッド、時計とキューの処理を始め、終了時は逆の順番で止める
  - `__main__.py`：設定 → セリフ集 → トークン → モデル → ホットキー → サーバーの順に起動する。例外や Ctrl+C でも、マイクを閉じ、ホットキーの登録を外す。ホットキーが 1 つも登録できなくても起動は続ける
  - `server.py`：デモとマイクを直接扱う経路をやめ、`Runtime` を lifespan の中で動かす。`hello` には `display` と今の `tension` を返す
  - `--demo`：偽の入力（`demo.py` の流れ。話して High → ホットキーでクリア → 黙って沈黙ハンター → キーワードで死亡、既定で約 1 分）を状態機械に入れる。マイク・Vosk・ホットキーは使わない
  - `hotkey.py`：`HotkeyListener` の Win32 API の既定を呼ぶときに決めるようにした（テストで本物のホットキーを登録しないため）

- T-13：反応の調整（Phase 2 のゲートで「セリフの間隔とキーワードの反応が遅い」とわかったため）
  - 吹き出しの最短間隔を 5 秒 → 3 秒にした（`state/constants.py` の `SAY_MIN_INTERVAL_MS`）
  - ST-05：High の間、High に入ってから（または前回の `Say(cheer)` から）15 秒ごとに `Say(cheer)` を出す（`CHEER_INTERVAL_MS`）。判定は `Tick` のたび。出口での優先度は `high` と同じ 2
    - 出口で捨てられても言ったものとして数え直す。ST-04 と同じ tick なら ST-04 を優先して言わない（state-machine.md の補足 9・10）
  - セリフ集に `[tension] cheer`（5 個）を追加し、必須のリストが 7 つになった。`cheer` のない自分のセリフ集は「[tension] cheer がありません」で起動しない（`config.example.toml` に追記）
  - キーワードを Vosk の部分結果（`PartialResult`）でも判定する。同じ種類の判定が 150 ms（`keywords.PARTIAL_HOLD_MS`）続いたら検知。1 つの発話（最終結果で区切る）につき 1 回まで。部分結果で検知しなかった発話は最終結果で判定する。時刻は `KeywordListener` の `clock` で差し替えられる
  - `--test-keywords` は、話し終わり（`detect` の `SpeechEnded`）から検知までの時間を `clear (-120 ms)` のように添える。話し終わる前の検知は、話し終わるまで表示を待って負の値で示す。認識した文字列は出さない
  - 手動確認（`--test-keywords` での検知までの時間・誤検知、OBS での盛り上げセリフと間隔）は未実施

## まだないもの

- 機能モジュール（log）
- CPU 使用率の計測（NFR-01）
- 死亡・クリアの演出（Phase 3）
- メンダコの本番の画像（今は仮の SVG）
- ログ出力先フォルダの存在確認・書き込み時のパス確認（ログのタスクで行う）

## 次にやること

- Phase 2 のゲート：`uv run stream-buddy` と exe で、OBS での手動確認（人間）
- Phase 3：死亡・クリアの画面演出、配信ログ

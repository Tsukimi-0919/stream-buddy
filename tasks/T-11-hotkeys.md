# タスク：ホットキー（RegisterHotKey）

- ID：T-11
- Phase：2
- 関連要件：FR-08（ホットキー）、FR-11（設定）、SR-05（キーロガーと疑われない作り）
- ブランチ名：`feat/hotkeys`

## 目的

決めたキー（既定は F9 / F10）が押されたら `Hotkey(kind)` を出す。
Windows の `RegisterHotKey` で**登録したキーだけ**を受け取り、それ以外のキー入力は一切見ない。

## 読む設計書

- `CLAUDE.md`
- `docs/requirements.md`（FR-08、SR-05）、`docs/threat-model.md`（SR-05）
- `docs/state-machine.md`（イベント：ホットキーは Cooldown 中も受け付ける）
- `src/stream_buddy/config.py`（`[hotkeys]`）、`src/stream_buddy/state/events.py`（`Hotkey`）
- `src/stream_buddy/audio.py`、`src/stream_buddy/keywords.py`（スレッドから `asyncio` へ渡す書き方の参考）

## 追加してよい依存

なし。Win32 API は標準ライブラリの `ctypes` で呼ぶ。キーボード関係のライブラリ（`keyboard`、`pynput`、`pywin32` など）は使わない。

## 仕様

### 設定の変更（`config.py`、`config.example.toml`）

- `[hotkeys]` の `death` / `clear` に、修飾キーとの組み合わせを書けるようにする
  - 形：`[Ctrl+][Alt+][Shift+]F1〜F12`（例：`"F9"`、`"Ctrl+Shift+F9"`）
  - 修飾キーは `Ctrl`・`Alt`・`Shift` だけ。順番は問わない。同じ修飾キーの重複はエラー。大文字・小文字は区別しない
  - `Win` キー、F1〜F12 以外のキー（文字・数字・Enter など）は**エラー**
  - `death` と `clear` が（修飾キーを含めて）同じならエラー
- 既定は `F9` / `F10` のまま
- `config.example.toml` のコメントに、「ゲームで F9 / F10 を使う場合は `Ctrl+Shift+F9` のように変える」「登録中はそのキーがほかのアプリに届かない」ことを書く

### ホットキーの受け取り（`src/stream_buddy/hotkey.py`）

- 専用のスレッドを1つ作り、その中で次を行う
  1. `RegisterHotKey(NULL, id, 修飾キー | MOD_NOREPEAT, 仮想キーコード)` で2つのキーを登録する（`MOD_NOREPEAT` で押しっぱなしの連続入力を防ぐ）
  2. `GetMessageW` でそのスレッドのメッセージを待ち、`WM_HOTKEY` が来たら id から `death` / `clear` を決めて `call_soon_threadsafe` で `Hotkey(kind)` を渡す
  3. 終わるときは `UnregisterHotKey` で必ず登録を外す
- 止めるときは、そのスレッドに `PostThreadMessageW(WM_QUIT)` を送る。終了時（Ctrl+C を含む）に必ず止まるようにする
- 登録に失敗したら（ほかのアプリが同じキーを使っているなど）、**そのキーだけ無効にして起動を続ける**。コンソールに「F9 はほかのアプリが使っているため登録できませんでした。config.toml で別のキーにしてください」のように、どのキーかを示して表示する
- `ctypes` の関数には `argtypes` と `restype` を設定し、`use_last_error=True` でエラーを取る
- Win32 API を呼ぶ部分は小さなクラスに分け、テストでは偽物に差し替えられるようにする（CI ではキーを押せないため）

### 使ってはいけないもの（SR-05）

`hotkey.py` だけでなく、`src/stream_buddy/` 全体で次を使わない。

- `SetWindowsHookEx`（キーボードのフック）
- `GetAsyncKeyState`、`GetKeyState`、`GetKeyboardState`（キーの状態を調べる）
- `RegisterRawInputDevices`（生の入力）
- キーボード関係のライブラリ

### 確認用のオプション

- `--test-hotkeys`：ホットキーだけを登録し、押されたら種類（`death` / `clear`）をコンソールに表示する。Ctrl+C で終わる
- `--demo` のときはホットキーを登録しない

### 組み立て

- `Brain` へのつなぎ込みは T-12。このタスクでは `--test-hotkeys` で動きを確かめられるところまで

## テスト

- 設定：`F9`・`F12`・`Ctrl+Shift+F9`・`shift+ctrl+f9`（順番と大小文字）が通る。`F13`・`A`・`Win+F9`・`Ctrl+Ctrl+F9`・`Ctrl+`・空文字がエラー。`death` と `clear` が修飾キーを含めて同じならエラー（`Ctrl+F9` と `F9` は別なので通る）
- 変換：キーの文字列から、修飾キーのビット（`MOD_ALT`・`MOD_CONTROL`・`MOD_SHIFT` ＋ `MOD_NOREPEAT`）と仮想キーコード（`VK_F1`〜`VK_F12`）が正しく作られる
- 偽の Win32 API で：
  - 起動で2つのキーが登録され、終了で2つとも登録が外れる（例外のときも）
  - `WM_HOTKEY` の id から正しい `Hotkey(kind)` が `asyncio` 側に届く
  - 片方の登録が失敗しても、もう片方は動き、失敗したキーが表示される
  - 停止で `WM_QUIT` が送られ、スレッドが終わる
- `src/stream_buddy/` のどのファイルにも、「使ってはいけないもの」の名前と、キーボード関係のライブラリの import がない（文字列で検査）
- `hotkey.py` が `RegisterHotKey`・`UnregisterHotKey`・`GetMessageW`・`PostThreadMessageW` 以外の `user32` の関数を使っていない（`user32.` の呼び出しを抜き出して照合する）

## やること

1. `feat/hotkeys` ブランチを作る
2. 設定を変更し、`hotkey.py` と `--test-hotkeys` を作る
3. テストを書く
4. `docs/requirements.md` の FR-08 と SR-05、`docs/threat-model.md` の SR-05 を、修飾キーと「使ってはいけないもの」に合わせて直す
5. `README.md` の注意事項に、「登録中はそのキーがほかのアプリに届かない」「ゲームと重なるときは設定で変える」を書く
6. 手動確認の手順を報告に書く（`--test-hotkeys`、ゲームやメモ帳を前面にしても反応すること、修飾キーの組み合わせ、ほかのアプリと重なったときの表示、exe での動作）
7. `docs/status.md` を更新する

## やらないこと

- `Brain` とのつなぎ込み（T-12）
- 設定画面、キーの記録機能（押されたキーを覚えさせるような機能は作らない）
- F1〜F12 以外のキー、`Win` キーへの対応

## 変更してよいファイル

- `src/stream_buddy/hotkey.py`（新規）
- `src/stream_buddy/config.py`、`src/stream_buddy/__main__.py`
- `config.example.toml`、`README.md`（注意事項のみ）
- `tests/` 配下（このタスクに関係するもの）
- `docs/requirements.md`、`docs/threat-model.md`、`docs/status.md`
- `tasks/T-11-hotkeys.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `uv run stream-buddy --test-hotkeys` で、F9 / F10 を押すと種類が表示される
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/hotkeys` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した

"""README の「導入」の節に、利用者が配布物を確かめるための説明があること (T-18)。"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
README = ROOT / "README.md"


def readme() -> str:
    return README.read_text(encoding="utf-8")


def powershell_blocks(text: str) -> list[str]:
    return re.findall(r"```powershell\n(.*?)```", text, re.DOTALL)


def test_sha256_command_uses_get_filehash_and_sha256_file() -> None:
    commands = [b for b in powershell_blocks(readme()) if "Get-FileHash" in b]
    assert commands, "README に Get-FileHash を使う PowerShell のコマンドがありません"
    command = commands[0]
    assert "-Algorithm SHA256" in command
    assert ".sha256" in command
    # バージョンごとに直さなくてよいよう、vX.Y.Z のまま書く
    assert "stream-buddy-vX.Y.Z-windows-x64.zip" in command


def test_attestation_command_is_documented() -> None:
    assert "gh attestation verify" in readme()
    assert "--repo Tsukimi-0919/stream-buddy" in readme()


SMARTSCREEN_IMAGES = ["docs/images/smartscreen-1.png", "docs/images/smartscreen-2.png"]


def test_readme_refers_to_smartscreen_images() -> None:
    text = readme()
    for image in SMARTSCREEN_IMAGES:
        assert f"]({image})" in text


def test_smartscreen_images_exist() -> None:
    for image in SMARTSCREEN_IMAGES:
        assert (ROOT / image).is_file(), f"{image} がありません"


def test_readme_local_images_exist() -> None:
    # README から参照している画像は、すべてリポジトリの中に実際にある
    images = re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", readme())
    assert images
    local = [i for i in images if not i.startswith(("http://", "https://"))]
    missing = [i for i in local if not (ROOT / i).is_file()]
    assert not missing, f"README の画像の参照先がありません: {missing}"


# T-21：OBS を先に開いたとき・モデルの置き場所


def section(text: str, heading: str) -> str:
    """見出し (行全体) から、同じか上の階層の次の見出しの前までを返す。"""
    level = len(heading) - len(heading.lstrip("#"))
    start = text.index(f"\n{heading}\n")
    end = re.search(rf"\n#{{1,{level}}} ", text[start + 1 :])
    return text[start : start + 1 + end.start()] if end else text[start:]


REFRESH = (
    "ブラウザソースを右クリック →「プロパティ」→ "
    "一番下の「現在のページのキャッシュを更新」を押してください"
)


def test_readme_does_not_mention_refresh_in_context_menu() -> None:
    # OBS のブラウザソースの右クリックのメニューには「更新」がない
    assert "右クリックして「更新」" not in readme()


def test_obs_section_recommends_starting_first_and_refresh() -> None:
    obs = section(readme(), "### 6. OBS の設定")
    assert "stream-buddy を先に起動" in obs
    assert REFRESH in obs


def test_model_section_has_folder_diagram() -> None:
    model = section(readme(), "## 音声認識モデルの取得（キーワード検知を使うとき）")
    for line in [
        "stream-buddy\\",
        "├─ stream-buddy.exe",
        "├─ _internal\\",
        "└─ models\\",
        "└─ vosk-model-small-ja-0.22\\",
        "├─ am\\",
        "├─ conf\\",
        "├─ graph\\",
        "├─ ivector\\",
    ]:
        assert line in model
    assert "1段深く" in model


def test_troubleshooting_section_covers_refresh_and_model() -> None:
    trouble = section(readme(), "## 困ったとき")
    assert REFRESH in trouble
    assert "探した場所" in trouble
    assert "1段深く" in trouble


def test_folder_diagram_matches_bundled_hash_list() -> None:
    # 図の中身は、同梱したハッシュの一覧 (公式のモデルの全ファイル) の 1 段目とそろえる
    from stream_buddy.keywords import load_hash_list

    top = {rel.split("/")[0] + ("\\" if "/" in rel else "") for rel in load_hash_list()}
    # 手順の番号の下にあるため、図は字下げされている
    block = re.search(r"```text\n *(stream-buddy\\\n.*?)```", readme(), re.DOTALL)
    assert block is not None
    lines = block.group(1).splitlines()
    model_at = next(i for i, line in enumerate(lines) if "vosk-model-small-ja-0.22\\" in line)
    shown = {line.split("─ ")[1] for line in lines[model_at + 1 :] if "─ " in line}
    assert shown == top

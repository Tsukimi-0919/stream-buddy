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


def test_readme_refers_to_smartscreen_images() -> None:
    text = readme()
    assert "](docs/images/smartscreen-1.png)" in text
    assert "](docs/images/smartscreen-2.png)" in text

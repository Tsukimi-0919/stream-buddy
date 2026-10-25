"""音量の列から「話し始め」「話し終わり」を判定する。

音声もネットワークも扱わない。時間はブロック数で数え、実時間には依存しない。
"""

import math

# しきい値を超えるブロックがこの回数続いたら話し始め (短いノイズで口パクしないように)
START_BLOCKS = 2
# しきい値以下がこの秒数続いたら話し終わり (語尾や息継ぎで口パクが途切れないように)
END_SILENCE_SECONDS = 0.3


def blocks_for(seconds: float, block_seconds: float) -> int:
    """秒数をブロック数に直す (端数は切り上げ。浮動小数の誤差で 1 増えないよう丸めてから)。"""
    return max(1, math.ceil(round(seconds / block_seconds, 6)))


class SpeechDetector:
    """ヒステリシスつきの発話検知。状態が変わったときだけ結果を返す。"""

    def __init__(self, threshold_db: float, block_seconds: float) -> None:
        self.threshold_db = threshold_db
        self.end_blocks = blocks_for(END_SILENCE_SECONDS, block_seconds)
        self.speaking = False
        self._run = 0

    def update(self, level_db: float) -> bool | None:
        """1 ブロック分の音量を受け取る。

        話し始めなら True、話し終わりなら False、変化がなければ None を返す。
        """
        loud = level_db > self.threshold_db
        if not self.speaking:
            self._run = self._run + 1 if loud else 0
            if self._run >= START_BLOCKS:
                return self._change(speaking=True)
        else:
            self._run = 0 if loud else self._run + 1
            if self._run >= self.end_blocks:
                return self._change(speaking=False)
        return None

    def _change(self, *, speaking: bool) -> bool:
        self.speaking = speaking
        self._run = 0
        return speaking

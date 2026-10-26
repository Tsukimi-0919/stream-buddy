"""docs/state-machine.md の数値。変えるときは state-machine.md を先に直す。

時間はすべてミリ秒。
"""

# 外から入れる tick の間隔 (Brain は tick を作らない。組み立て側の目安)
TICK_MS = 100

# テンション (ST-01〜ST-04)
TENSION_WINDOW_MS = 30_000  # 話していた割合を数える窓
CALM_TO_NORMAL = 35  # ST-01: これ以上で Normal へ
NORMAL_TO_CALM = 20  # ST-02: これ未満で Calm へ
NORMAL_TO_HIGH = 70  # ST-03: これ以上で High へ
HIGH_TO_NORMAL = 50  # ST-04: これ未満で Normal へ
TENSION_HOLD_MS = 5_000  # 状態を変えたあと (と起動直後)、変えない時間
CLEAR_BONUS = 30  # クリアの加点
DEATH_BONUS = -30  # 死亡の減点
BONUS_DECAY_MS = 10_000  # 加点・減点が直線的に 0 に戻るまでの時間
TENSION_MIN = 0
TENSION_MAX = 100

# 沈黙ハンター (ST-11〜ST-15)
DEFAULT_SILENCE_SECONDS = 20  # 最初の待ち時間の既定値。実際の値は設定の silence.seconds から渡す
SILENCE_WAIT_MULTIPLIER = 2  # 話しかけるたびに待ち時間を何倍にするか
SILENCE_MAX_CALLS = 3  # この回数話しかけたら打ち止め

# イベント (ST-21〜ST-25)
EFFECT_MS = 3_000  # 演出の長さ (演出開始から)
EVENT_COOLDOWN_MS = 10_000  # キーワードを受け付けない時間 (演出開始から)

# 出口
SAY_MIN_INTERVAL_MS = 5_000  # high / silence の吹き出しの最短間隔 (暫定)

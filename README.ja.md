# operantkit-cli

:gb: [English README](README.md)

OperantKit セッションのエンドツーエンド・コマンドライン・エントリポイント。

`operantkit-cli` は OperantKit 実験スタックを束ねる:

```
contingency-dsl-py  →  DSL 文字列をパース
contingency-py      →  AST → ランタイム Schedule 変換
session-runner      →  Session 駆動
experiment-io       →  virtual / serial / HIL HW ポーリング
session-recorder    →  イベントを OKL v1 ログに永続化
```

## インストール

```bash
pip install operantkit-cli
```

`operant` コマンドと、それが駆動する OperantKit の 6 ライブラリ
（contingency-dsl-py、contingency-py、experiment-core、session-runner、
session-recorder、experiment-io）が一緒に入る。

### 開発

```bash
mise exec -- python -m venv .venv
mise exec -- .venv/bin/python -m pip install -e '.[dev]'
```

兄弟の OperantKit ライブラリがパッケージインデックスから取れない場合は、
それらの wheel を 1 つのディレクトリに置き、pip にそのディレクトリを渡す:

```bash
mise exec -- .venv/bin/python -m pip install --find-links <wheel-dir> -e '.[dev]'
```

## 30 秒で動く例

固定時隔 30 秒（FI 30 s）スケジュールを組み込みの仮想被験体に対して実行し、強化子が 5 回呈示されたら止める:

```bash
operant run --schedule "FI30s" --output fi30.okl --exit-reinforcers 5
grep -v '^#' fi30.okl | cut -f2 | sort | uniq -c
#    5 reinforcer_end
#    5 reinforcer_start
#  132 response
#   12 state_change
tail -n 1 fi30.okl
# 154.56400194973696	state_change	RUNNING	FINISHED
```

セッション時間は模擬時計で進むので、上の 155 秒のセッションは壁時計で約 0.1 秒で終わり、何度実行しても同じログになる（仮想被験体は `--seed`、既定 `0` で固定される）。`fi30.okl` の先頭には、DSL ソースと各イベント種の列構成を記録したヘッダが付く:

```
# OKL v1
# session_name = "session"
# clock_type = "ManualClock"
# session_start = 0.0
# meta:
#   dsl = "FI30s"
# events:
#   response          : id:int operandum:int?
#   reinforcer_start  : id:int potency:float operandum:int?
...
# ---
0.0	state_change	IDLE	RUNNING
1.8606071110652234	response	1	-
```

ログの解析は [session-analyzer](https://github.com/OperantKit/session-analyzer)（`pip install session-analyzer`）で行う。

## 自作の 50 行では足りない理由

反応を発生させてスケジュールを判定するだけの短いスクリプトは、セッションを報告できる形にする部分をたいてい欠く:

- **どの手続きも 1 つのスケジュール記法で書ける。** `--schedule` は [contingency-py](https://github.com/OperantKit/contingency-py) が変換できる [contingency-dsl](https://github.com/OperantKit/contingency-dsl) の式をすべて受け付ける。並立スケジュールなどの複合スケジュールや、`@algorithm("fleshler-hoffman", n=12, seed=42)` のようなプログラム注釈も含む。VI / VR / VT の値はその場しのぎの乱数ではなく Fleshler-Hoffman (1962) の数列から作る。
- **並立スケジュールの成分ごとに操作体が 1 つ。** `Conc(...)` では成分ごとに仮想操作体と独立した Poisson 反応源（seed は `--seed`、`--seed + 1`、...）が付くので、すべての成分が反応にさらされる。
- **再現できる実行。** DSL に `@algorithm(..., seed=N)` を書き `--seed` を固定すれば、2 回の実行がバイト単位で同じログを書く。
- **自己記述的なログ。** OKL v1 のヘッダに、セッション名・時計の種類・DSL ソース・各イベント種（`response`、`reinforcer_start`、`reinforcer_end`、`state_change`、`component_change`、`phase_enter`、`phase_exit`）の列構成が残る。
- **入力の誤りはセッション開始前に止まる。** 不正なスケジュールや終了条件は `operant: error: ...` を 1 行出して終了コード 2 で終わり、ログファイルを作らない。

## 使い方

```bash
operant run --schedule "FR3" \
    --output fr3.okl \
    --exit-reinforcers 5 \
    --virtual-rate-hz 5.0
```

`--schedule` は `contingency_dsl.parse` + `contingency.bridge.from_dsl`
が受理する任意の式を受け付ける（例: `"FI30s"`,
`"Conc(VI30s, VI60s)"`）。終了条件は `--exit-reinforcers N` か
`--exit-time SECONDS` のいずれか（排他）。モジュール経由の起動も可:
`python -m operantkit_cli run ...`。

プログラム全体に付く注釈（`@clock` など）も書ける。VI / VR / VT の
セッションを再現可能にするには、DSL 自体に seed を書く:

```bash
operant run --schedule $'@algorithm("fleshler-hoffman", n=12, seed=42)\nConc(VI30s, VI60s)' \
    --output conc.okl --exit-time 1800 --seed 0
```

各成分には記述順に seed 42, 43, ... が割り当てられる。`--seed` が固定するのは
仮想被験体の反応だけである。VI / VR / VT の値は Fleshler-Hoffman でのみ生成し、
`@algorithm("arithmetic")` はエラーになる。

## サブコマンド

### `run`

仮想 Poisson 被験体に対してセッションを実行し OKL v1 ログを書き出す。

| フラグ | 既定 | 意味 |
|---|---|---|
| `--schedule DSL` | 必須 | contingency-dsl ソース。 |
| `--output PATH` | 必須 | OKL v1 ログの出力パス。 |
| `--exit-reinforcers N` | （いずれか必須） | N 回の強化子で停止。 |
| `--exit-time SECONDS` |  | SECONDS のセッション時間で停止。 |
| `--name NAME` | `session` | セッションラベル。 |
| `--virtual-rate-hz HZ` | `1.0` | 仮想被験体の Poisson rate。 |
| `--seed N` | `0` | 被験体 RNG シード。 |
| `--reinforcer-duration SEC` | `0.5` | 各呈示の保持時間。 |
| `--poll-interval SEC` | `0.001` | アイドル時のクロック前進量。 |
| `--max-steps N` | `5000` | ループ反復上限。 |
| `--max-duration SEC` | なし | 任意の壁時計時間上限。 |

## 開発

```bash
.venv/bin/pytest
.venv/bin/pytest --cov=src --cov-report=term-missing
.venv/bin/ruff check src tests
.venv/bin/black --check src tests
```

## 延期された機能

- `--config FILE.yaml` — 完全な session-spec を宣言的に読み込むローダ
  （別パッケージ `schedule-dsl` 待ち）。
- `--backend {serial,hil}` — `experiment-io` 側は対応済みだが CLI は
  現時点で virtual backend のみを公開。
- 決定論的な実スケジュールに対するスナップショットテスト。

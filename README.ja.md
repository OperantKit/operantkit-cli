# operantkit-cli

:gb: [English README](README.md)

OperantKit セッションのエンドツーエンド・コマンドライン・エントリポイント。

`operantkit-cli` は OperantKit 実験スタックを束ねる:

```
contingency-dsl-py  →  DSL 文字列をパース
contingency-py      →  AST → ランタイム Schedule 変換
session-runner      →  Session 駆動
experiment-io       →  virtual / serial / HIL HW ポーリング
session-recorder    →  イベントを JSONL に永続化
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
| `--output PATH` | 必須 | JSONL 出力パス。 |
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

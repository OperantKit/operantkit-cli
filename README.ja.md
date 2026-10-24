# operantkit-cli

:gb: [English README](README.md)

`operant run` は、強化スケジュール 1 つのセッションを仮想被験体に対して実行し、すべてのイベントをテキストのログに書き出すコマンドです。コードを書く必要はありません。[OperantKit](https://github.com/OperantKit) のコマンドラインの入口で、スケジュールを contingency-dsl-py で解析し、contingency-py・experiment-core・session-runner・experiment-io で実行し、session-recorder でログを書きます。

- **式 1 つでログ 1 つ。** `--schedule "Conc(VI30s, VI60s, COD=2s)"` が手続きのすべてです。
- **数時間ではなく数秒。** セッション時間は模擬時計で進み、同じ seed なら同じログがバイト単位で書かれます。
- **誤りはセッションの前に止まります。** 不正なスケジュールはエラーを 1 行出し、ログを書きません。

動物を走らせる前にスケジュールのプログラムが実際に何を提示するかを確かめる、授業用の例データを作る、中身の分かったログを分析の流れに流す、といった用途に使います。

## インストール

Python 3.11 以上が必要です。各パッケージはまだ PyPI に登録されていないので、GitHub から依存の解決なしで入れます:

```bash
G=git+https://github.com/OperantKit
pip install --no-deps $G/contingency-dsl-py $G/contingency-py $G/experiment-core \
  $G/session-runner $G/session-recorder $G/experiment-io $G/operantkit-cli
```

外部のライブラリは要りません。`pip check` はこれら開発版どうしのバージョンの食い違いを報告しますが、このコマンドの動作には影響しません。

## 30 秒で動く例

固定時隔（FI）30 秒スケジュールを組み込みの仮想被験体に対して実行し、強化子が 5 回提示されたら止めます:

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

155 秒のセッションが壁時計で 1 秒もかからずに終わり、もう一度実行しても同じファイルが書かれます。`fi30.okl` は OKL（OperantKit Log）形式のファイルで、スケジュールの式と各イベント種の列を記録したヘッダの後に、イベントごとにタブ区切りの 1 行が続きます。

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

ログの描画や分析には [session-analyzer](https://github.com/OperantKit/session-analyzer) を使います。

## 使い方

`operant` のサブコマンドは `run` の 1 つです。`--schedule` には、[contingency-py](https://github.com/OperantKit/contingency-py) が実行できる [contingency-dsl](https://github.com/OperantKit/contingency-dsl) の式を何でも渡せます（例: `"FR3"`、`"VI60s"`、`"Conc(VI30s, VI60s, COD=2s)"`。COD は切替遅延）。`--exit-reinforcers` と `--exit-time` のどちらか一方だけを指定します。`python -m operantkit_cli run ...` も同じコマンドです。

| フラグ | 既定値 | 意味 |
|---|---|---|
| `--schedule DSL` | 必須 | contingency-dsl の式 |
| `--output PATH` | 必須 | 書き出す OKL ログのパス |
| `--exit-reinforcers N` | この 2 つのどちらかが必須 | 強化子 N 回で停止 |
| `--exit-time SECONDS` | | セッション時間 SECONDS 秒で停止 |
| `--name NAME` | `session` | ヘッダに書くセッション名 |
| `--virtual-rate-hz HZ` | `1.0` | 仮想被験体の反応率（毎秒の反応数） |
| `--seed N` | `0` | 仮想被験体の反応の seed |
| `--reinforcer-duration SEC` | `0.5` | 強化子 1 回の提示時間 |
| `--poll-interval SEC` | `0.001` | 待機中の 1 ステップで時計を進める量 |
| `--max-steps N` | 自動 | ループのステップ数の上限（「制限」を参照） |
| `--max-duration SEC` | なし | 壁時計時間の上限（任意） |

**並立スケジュール。** `Conc(...)` の各成分には、それぞれ専用の仮想オペランダム（被験体が反応するレバーやキー）と、seed が `--seed`、`--seed + 1`、… の独立した反応源が付きます。

**再現できる VI・VR・VT の値。** 変動値は Fleshler と Hoffman (1962) の数列に従います。`--seed` が固定するのは被験体の反応だけなので、スケジュールの値を固定するには式の中で seed を指定します:

```bash
operant run --schedule $'@algorithm("fleshler-hoffman", n=12, seed=42)\nConc(VI30s, VI60s)' \
    --output conc.okl --exit-time 1800 --seed 0
```

各成分には書いた順に seed 42、43、… が割り当てられます。

## 制限

- **仮想被験体のみ。** 被験体は一定の Poisson 率で反応し、強化によって変化しません。そのためログが示すのはスケジュールのプログラムが何を提示するかであって、動物がどう振る舞うかではありません。シリアルポートと HIL（hardware-in-the-loop、実機を回路ごとつないだ検証）のバックエンドは [experiment-io](https://github.com/OperantKit/experiment-io) にありますが、このコマンドからは選べません。
- **ステップ数の上限。** 反応 1 回と強化子の提示 1 回がそれぞれループの 1 ステップです。`--exit-time` のときの既定の上限はセッション時間と反応率から決まるので、セッションは時間の上限で終わります。`--exit-reinforcers` のときの既定の上限は 1,000,000 ステップで、強化子を提示しないスケジュール（例: `EXT`）が止まらなくなるのを防ぎます。上限に達したセッションは `RuntimeError: drive: did not finish within N steps` で止まり、途中までのログが残ります。必要なら `--max-steps N` で大きな値を指定してください。
- **Fleshler–Hoffman のみ。** `@algorithm("arithmetic")` はエラーになります。
- **時刻は模擬時間です。** ログの時刻は模擬時計上のセッション時間で、壁時計の時刻ではありません。

このコマンドを AI のコーディング支援ツールに使わせる場合は [AGENTS.md](AGENTS.md) を参照してください。

## 開発

このリポジトリを clone し、上の `--no-deps` のコマンドで他のパッケージを入れた後で:

```bash
pip install --no-deps -e .
pip install pytest pytest-cov
pytest
```

`tests/test_readme_examples.py` は両方の README の「30 秒で動く例」を実行し、そこに書かれた件数と最終行を照合します。

## 参考文献

Fleshler, M., & Hoffman, H. S. (1962). A progression for generating variable-interval schedules. *Journal of the Experimental Analysis of Behavior*, *5*(4), 529–530. https://doi.org/10.1901/jeab.1962.5-529

## ライセンス

MIT。[LICENSE](LICENSE) を参照してください。

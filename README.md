# US Tech Quant v21

**Research-first quantitative ranking, validation, and daily signal pipeline for U.S. equities and ETFs.**

US Tech Quant v21 is a Windows-first quantitative research system built with Python and PowerShell. It automates market-data validation, feature generation, multi-strategy stock ranking, historical testing, audit reporting, and guarded daily refresh workflows.

The project is designed for **reproducible research rather than direct trading execution**.

> **Version note**
>
> The public project name remains **US Tech Quant v21**.
> Some internal scripts and pipeline components use higher implementation identifiers such as `V22.xxx`. These identifiers describe internal workflow revisions and do not represent a change to the public release name.

---

## Overview

The system converts raw market data into auditable daily research outputs through a structured pipeline:

```text
Market Data
    ↓
Data Validation
    ↓
Feature Engineering
    ↓
ABCDE Strategy Scoring
    ↓
Cross-Sectional Ranking
    ↓
Same-Date Comparability Checks
    ↓
Top-20 Research Output
    ↓
Historical and Random-Window Validation
```

The current workflow covers more than 300 U.S. equities and ETFs and is designed to answer four practical research questions:

1. Which stocks rank highest under each strategy today?
2. Are all strategy outputs based on the same market date?
3. Do the signals remain effective across different historical periods?
4. Can every result be reproduced and audited from local artifacts?

---

## Core Features

### Daily Research Pipeline

The daily pipeline performs:

* raw and adjusted price refresh
* ticker-universe validation
* missing-data and duplicate checks
* feature construction
* ABCDE strategy scoring
* Top-20 ranking generation
* raw-score preservation
* same-date comparability validation
* summary and audit artifact generation
* hard-gate acceptance or rejection

The current stable daily entry point is:

```powershell
.\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

A successful run returns:

```text
PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN
```

The guard layer prevents incomplete or inconsistent daily outputs from being treated as accepted research results.

---

## ABCDE Strategy Framework

The system produces five independently scored rankings.

| Strategy            | Purpose                                       |
| ------------------- | --------------------------------------------- |
| `A1_CONTROL`        | Baseline multi-factor control strategy        |
| `B_STATIC_MOMENTUM` | Momentum-oriented ranking                     |
| `C`                 | Alternative factor-weight configuration       |
| `D`                 | Diversified or defensive factor configuration |
| `E_R1`              | Experimental research strategy                |

Each strategy produces:

* signal date
* ticker
* rank
* raw score
* normalized research fields
* Top-20 summary
* strategy-level diagnostics

The system preserves the original raw score rather than publishing only the final rank.

Example output:

```text
Rank  Ticker  RawScore
1     AAPL    0.898364
2     PANW    0.884938
3     PYPL    0.883704
```

---

## Factor Architecture

The research framework is organized around six factor families:

```text
Fundamental
Technical
Strategy
Risk
Market Regime
Data Trust
```

Technical inputs may include:

* relative strength
* momentum
* RSI
* KDJ
* Bollinger Bands
* moving averages
* exponential moving averages
* volume behavior
* volatility
* breakout strength
* drawdown characteristics

The final score is constructed from multiple factor families rather than from a single technical indicator.

---

## Same-Date Comparability

A ranking comparison is accepted only when all required strategies use the same canonical market date.

The daily guard checks fields such as:

```text
canonical_latest_date
abcde_latest_date
dram_latest_price_date
same_date_comparable_all_strategies
hard_gate_passed
```

A result is rejected when:

* one strategy is stale
* price data are incomplete
* the ranking date differs across strategies
* required output files are missing
* a child pipeline exits with an error
* integrity checks fail

This prevents rankings from different market dates from being compared as though they were generated simultaneously.

---

## Historical Validation

The project includes several forms of validation.

### Fixed-Period Backtests

Used to evaluate a strategy over a defined historical interval.

### Random-Window Backtests

Random starting dates are used to reduce dependence on a single favorable backtest period.

Supported research horizons include:

```text
20 trading days
60 trading days
120 trading days
252 trading days
504 trading days
```

### Year-Stratified Testing

Windows can be sampled independently within each calendar year to test whether performance is concentrated in a specific market regime.

### Benchmark Comparison

QQQ is used as the primary benchmark for technology-oriented strategy research.

Typical evaluation fields include:

* median return
* median excess return
* probability of beating QQQ
* maximum drawdown
* worst-window return
* turnover
* transaction-cost-adjusted return
* year-by-year stability

---

## Example Portfolio Rule

One researched portfolio rule is:

```text
Enter: ticker reaches Top 5
Exit: ticker falls below Top 10
Maximum holdings: 5
Initial allocation: 20% per slot
Replacement source: current Top 5 only
Rebalancing: disabled between entry and exit
Benchmark: QQQ
Transaction cost: configurable
```

This rule is a research configuration, not a guaranteed or recommended trading strategy.

The repository also contains infrastructure for testing alternative:

* entry thresholds
* exit thresholds
* holding periods
* replacement rules
* turnover controls
* regime filters
* benchmark fallback rules

---

## Audit and Research Integrity

The project emphasizes failure visibility rather than silently producing a result.

Audit checks include:

* duplicated ticker-date rows
* missing price fields
* stale snapshots
* inconsistent strategy dates
* invalid universe membership
* unexpected ticker deletion
* strategy-specific window deletion
* signal leakage risks
* output-file completeness
* frozen-configuration verification
* transaction lifecycle integrity
* forced-exit accounting
* benchmark-window consistency

Where complete historical point-in-time data are unavailable, the limitation is reported rather than hidden.

---

## Quick Start

### Requirements

* Windows 10 or Windows 11
* PowerShell 5.1 or later
* Python 3.10 or later
* Git
* local market-data source or compatible cached dataset

### Clone the Repository

```powershell
git clone https://github.com/kinryukii/us-tech-quant-v21.git
cd us-tech-quant-v21
```

### Create a Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Install project dependencies when a requirements file is available:

```powershell
pip install -r requirements.txt
```

### Allow Local PowerShell Scripts

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### Run the Daily Research Chain

```powershell
.\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

### Check Repository Status

```powershell
git status
```

---

## Repository Structure

A simplified project layout:

```text
us-tech-quant-v21/
├─ scripts/
│  ├─ v21/
│  └─ v22/
│     ├─ daily pipeline entry points
│     ├─ ranking and validation modules
│     ├─ random-window backtests
│     ├─ annual stability diagnostics
│     └─ regression tests
├─ config/
│  └─ strategy and runtime configuration
├─ docs/
│  └─ methodology and research notes
├─ tests/
│  └─ validation and regression tests
└─ README.md
```

Large datasets, generated outputs, logs, virtual environments, and local caches are intentionally excluded from Git.

Typical excluded content includes:

```text
data/
outputs/
results/
.venv/
__pycache__/
*.log
*.parquet
```

---

## Data Storage

The repository is designed to separate source code from large research data.

Recommended structure:

```text
Project code:
D:\us-tech-quant

Market data:
D:\us-tech-quant-data

Backtest and archived results:
D:\us-tech-quant-results
```

This separation provides:

* a smaller Git repository
* faster commits and cloning
* independent backtest result directories
* reduced risk of accidentally publishing proprietary or large datasets
* clearer separation between code, data, and generated research artifacts

---

## Reproducibility

For reproducible research, each run should preserve:

* strategy configuration
* ticker universe
* signal date
* data date
* random seed
* transaction-cost assumptions
* benchmark series
* test-window manifest
* summary JSON
* ranking CSV
* integrity diagnostics

Randomized tests should always use an explicitly recorded seed.

Example:

```text
MASTER_SEED=2026071604
```

A result without its configuration, seed, date range, and universe definition should not be treated as independently reproducible.

---

## Current Research Status

The current system can:

* run the daily ABCDE ranking workflow
* generate five same-date-comparable strategy rankings
* print Top-20 tickers with raw scores
* maintain local historical price caches
* run fixed and random-window backtests
* compare strategy performance with QQQ
* test annual stability
* measure turnover and drawdown
* reject incomplete daily runs
* preserve machine-readable audit summaries

The research results also show that a ranking signal can perform differently across years and market regimes. Therefore, the project does not treat a strong aggregate backtest as sufficient evidence of a robust strategy.

---

## Known Limitations

The public repository should not be interpreted as a complete institutional-grade point-in-time research platform.

Current limitations may include:

* incomplete historical index membership
* survivorship-bias risk
* incomplete delisted-security coverage
* limited historical publication-date fundamentals
* incomplete historical corporate-action metadata
* dependence on local data availability
* broker or vendor-specific data differences
* simplified transaction-cost and liquidity assumptions
* limited live-execution validation

Historical proxy rankings must be distinguished from rankings reconstructed using complete point-in-time data.

---

## Safety and Execution Policy

This repository is research-first.

By default:

```text
broker_action_allowed = False
official_adoption_allowed = False
```

Research output must not automatically trigger:

* live orders
* portfolio reallocation
* broker actions
* official strategy adoption

Any future execution layer should remain isolated behind explicit configuration, additional validation, and manual approval.

---

## Roadmap

Planned research directions include:

* stronger point-in-time data support
* historical universe reconstruction
* delisted-security coverage
* improved fundamental-data lineage
* walk-forward validation
* strategy ensemble analysis
* factor-decay measurement
* market-regime attribution
* turnover-aware portfolio construction
* transaction-cost stress testing
* paper-trading isolation
* automated PDF research reports
* multi-agent research workflows

---

## Disclaimer

This repository is provided for software engineering, quantitative research, and educational purposes only.

It does not constitute:

* investment advice
* a solicitation to trade
* a guarantee of future performance
* a production-ready trading system

Backtested or simulated performance does not represent actual trading results. Historical results may be affected by data quality, survivorship bias, look-ahead bias, market impact, liquidity constraints, transaction costs, and implementation assumptions.

Use the software and research outputs at your own risk.

---

## Project

**US Tech Quant v21**

Quantitative ranking, validation, backtesting, and guarded daily research infrastructure for U.S. equities and ETFs.








# US Tech Quant v21

**米国株式および ETF を対象とした、リサーチ優先型の定量ランキング・検証・日次シグナル基盤。**

US Tech Quant v21 は、Windows、Python、PowerShell を中心に構築された定量リサーチシステムです。

市場データの検証、特徴量生成、複数戦略によるスコアリング、銘柄ランキング、過去検証、ランダム期間バックテスト、監査レポート、保護された日次更新フローを自動化します。

本プロジェクトは、**実売買を直接行う自動取引システムではなく、再現可能な定量リサーチ基盤**として設計されています。

> **バージョン表記について**
>
> 本プロジェクトの公開バージョン名は、引き続き **US Tech Quant v21** です。
>
> リポジトリ内部の一部スクリプトやパイプラインでは、`V22.xxx` などの内部実装番号を使用しています。
>
> これらはモジュール、検証工程、ワークフローの改訂番号を示すものであり、公開プロジェクト名が v22 に変更されたことを意味しません。

---

## プロジェクト概要

本システムは、構造化され監査可能なリサーチパイプラインを通じて、元の市場データを日次の定量リサーチ結果へ変換します。

```text
市場データ
    ↓
データ整合性検証
    ↓
特徴量エンジニアリング
    ↓
ABCDE 複数戦略スコアリング
    ↓
クロスセクション銘柄ランキング
    ↓
同一日付比較可能性チェック
    ↓
Top 20 リサーチ結果
    ↓
過去検証およびランダム期間検証
```

現在のシステムは、300 銘柄を超える米国株式および ETF を対象とし、主に以下の問いに答えることを目的としています。

1. 本日、各戦略で最も高く評価された銘柄は何か
2. すべての戦略結果が同一の市場日付に基づいているか
3. シグナルが異なる年や市場環境でも安定しているか
4. すべてのランキングおよび検証結果を再実行・追跡・監査できるか

---

## 主な機能

### 日次定量リサーチパイプライン

日次パイプラインでは、主に以下を実行します。

* 未調整価格データおよび調整済み価格データの更新
* 銘柄ユニバースの整合性確認
* 欠損データ確認
* ticker-date 重複確認
* 特徴量生成
* ABCDE 5 戦略のスコア計算
* Top 20 ランキング生成
* 元スコアの保存
* 5 戦略の同一日付比較可能性検証
* JSON、CSV、ログ形式の監査出力
* ハードゲートによる採否判定
* 不完全な結果の自動拒否

現在の安定した日次実行用エントリーポイントは以下です。

```powershell
.\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

正常終了時には、以下のステータスが返されます。

```text
PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN
```

Guard レイヤーは、日付不一致、データ不足、子プロセス失敗、出力欠落などの問題を含む結果が、有効なリサーチ結果として扱われることを防止します。

---

## ABCDE 5 戦略フレームワーク

システムは毎日、5 種類の独立したスコアリング結果およびランキングを生成します。

| 戦略                  | 主な役割                |
| ------------------- | ------------------- |
| `A1_CONTROL`        | 複数因子を用いた基準コントロール戦略  |
| `B_STATIC_MOMENTUM` | トレンドおよびモメンタム重視戦略    |
| `C`                 | 代替的な因子ウェイト構成        |
| `D`                 | 分散、守備性、リスク制約を重視した構成 |
| `E_R1`              | 実験的リサーチ戦略           |

各戦略は以下を出力します。

* シグナル日
* ティッカー
* ランク
* 元スコア
* 標準化されたリサーチ項目
* Top 20 サマリー
* 戦略単位の診断情報

システムは最終順位だけでなく、各銘柄の元スコアも保存します。

例：

```text
Rank  Ticker  RawScore
1     AAPL    0.898364
2     PANW    0.884938
3     PYPL    0.883704
```

元スコアを保存することで、順位だけでは分からない銘柄間の実質的な評価差を確認できます。

---

## 因子アーキテクチャ

現在の評価フレームワークは、主に以下の 6 種類の因子群から構成されています。

```text
ファンダメンタル因子
テクニカル因子
戦略因子
リスク因子
市場レジーム因子
データ信頼性因子
```

テクニカル入力には、以下が含まれる場合があります。

* 相対強度
* モメンタム
* RSI
* KDJ
* ボリンジャーバンド
* 移動平均線
* 指数移動平均線
* 出来高動向
* ボラティリティ
* ブレイクアウト強度
* ドローダウン特性
* ベンチマーク比の相対パフォーマンス

最終スコアは、単一のテクニカル指標ではなく、複数の因子群を組み合わせて構成されます。

---

## 同一日付比較可能性

すべての戦略が同じ基準市場日に基づいて生成された場合のみ、戦略間の横比較を許可します。

日次 Guard は、以下のような項目を確認します。

```text
canonical_latest_date
abcde_latest_date
dram_latest_price_date
same_date_comparable_all_strategies
hard_gate_passed
```

以下のケースでは当日の結果が拒否されます。

* 一部戦略が古い日付を使用している
* 価格データの更新が完了していない
* 戦略ごとのランキング日が一致していない
* 必須出力ファイルが欠落している
* 子パイプラインが異常終了している
* データ整合性検証に失敗している
* 銘柄ユニバース数が想定と一致しない
* ランキング結果が不完全である

これにより、異なる市場日に生成されたランキングを同時点の結果として誤比較することを防止します。

---

## 過去検証フレームワーク

本プロジェクトには、複数の検証方式が含まれています。

### 固定期間バックテスト

指定された過去期間における戦略パフォーマンスを検証します。

### ランダム期間バックテスト

過去データから開始日をランダムに抽出し、単一の都合のよいバックテスト期間への依存を軽減します。

現在の代表的な検証期間は以下です。

```text
20 取引日
60 取引日
120 取引日
252 取引日
504 取引日
```

### 年別層化ランダム検証

各暦年内で独立してランダム期間を抽出し、戦略成績が特定の年や市場局面に集中していないかを検証します。

### ベンチマーク比較

テクノロジー・グロース系戦略の主要ベンチマークとして、現在は QQQ を使用しています。

代表的な評価指標は以下です。

* リターン中央値
* QQQ に対する超過リターン中央値
* QQQ を上回った期間の割合
* 最大ドローダウン
* 最悪期間リターン
* 売買回転率
* 取引コスト控除後リターン
* 年別安定性
* 保有期間別の一貫性

---

## ポートフォリオルール例

現在検証されているポートフォリオルールの一例は以下です。

```text
買付条件：銘柄が Top 5 に入る
売却条件：銘柄が Top 10 圏外へ下落する
最大保有数：5 銘柄
初期配分：1 銘柄あたり 20%
補充候補：現在の Top 5 のみ
保有中の再均衡：無効
ベンチマーク：QQQ
取引コスト：設定可能
```

これはリサーチおよびバックテスト用の設定であり、投資助言や収益保証を意味するものではありません。

リポジトリには、以下の条件を検証するための基盤も含まれています。

* 異なる買付順位閾値
* 異なる売却順位閾値
* 異なる保有期間
* 異なる銘柄補充ルール
* 売買回転率制御
* 市場レジームフィルター
* QQQ フォールバック
* 非リバランス運用
* 取引コストのストレステスト

---

## 監査およびリサーチ整合性

本プロジェクトは、異常時にも結果を出し続けるのではなく、失敗を明示的に可視化することを重視しています。

主な監査項目は以下です。

* ticker-date 重複レコード
* 始値または終値の欠損
* 古いスナップショット
* 戦略間の日付不一致
* ユニバース構成銘柄の異常
* 想定外のティッカー削除
* 戦略固有の検証期間削除
* 先読みバイアスのリスク
* データリーケージのリスク
* 出力ファイルの完全性
* 凍結済み設定の一致確認
* 売買ライフサイクルの完全性
* 強制終了処理の監査
* 売買回転率計算の検証
* ベンチマーク期間の一致
* ランダムシードの保存
* バックテスト期間 manifest の保存

完全な point-in-time データが利用できない場合、その制約を明記し、代理的な過去検証を厳密な歴史再構成として扱わない方針を採用しています。

---

## クイックスタート

### 動作環境

* Windows 10 または Windows 11
* PowerShell 5.1 以上
* Python 3.10 以上
* Git
* ローカル市場データソース、または互換性のあるキャッシュデータ

### リポジトリのクローン

```powershell
git clone https://github.com/kinryukii/us-tech-quant-v21.git
cd us-tech-quant-v21
```

### Python 仮想環境の作成

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

依存関係ファイルが存在する場合は、以下を実行します。

```powershell
pip install -r requirements.txt
```

### PowerShell スクリプトの一時許可

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 日次リサーチチェーンの実行

```powershell
.\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

### Git 状態の確認

```powershell
git status
```

---

## リポジトリ構成

簡略化した構成例は以下です。

```text
us-tech-quant-v21/
├─ scripts/
│  ├─ v21/
│  └─ v22/
│     ├─ 日次パイプラインのエントリーポイント
│     ├─ ランキングおよび検証モジュール
│     ├─ ランダム期間バックテスト
│     ├─ 年別安定性診断
│     └─ 回帰テスト
├─ config/
│  └─ 戦略および実行設定
├─ docs/
│  └─ 手法説明およびリサーチノート
├─ tests/
│  └─ 整合性および回帰テスト
└─ README.md
```

大容量データ、実行結果、ログ、仮想環境、ローカルキャッシュは GitHub に含めない設計です。

代表的な除外対象は以下です。

```text
data/
outputs/
results/
.venv/
__pycache__/
*.log
*.parquet
```

---

## データ保存方針

本プロジェクトでは、ソースコード、市場データ、バックテスト結果を分離して保存することを推奨しています。

推奨構成：

```text
プロジェクトコード：
D:\us-tech-quant

市場データおよびリサーチデータ：
D:\us-tech-quant-data

バックテスト結果および履歴アーカイブ：
D:\us-tech-quant-results
```

この構成には以下の利点があります。

* Git リポジトリを小さく保てる
* コミットおよびクローンを高速化できる
* 大容量の市場データを誤って公開するリスクを抑えられる
* 各バックテスト結果を独立して保存できる
* コード、原データ、生成物の境界が明確になる
* コアコードに影響を与えず古い結果を整理できる

---

## 再現可能性

リサーチ結果の再現性を確保するため、各実行では以下の情報を保存することを推奨します。

* 戦略設定
* 銘柄ユニバース定義
* シグナル日
* 市場データ日
* ランダムシード
* 取引コスト前提
* ベンチマーク系列
* 検証期間一覧
* サマリー JSON
* ランキング CSV
* データ整合性診断
* Git commit またはコードバージョン

ランダム検証では、ランダムシードを明示的に記録します。

例：

```text
MASTER_SEED=2026071604
```

設定、期間、ユニバース、データバージョン、ランダムシードが保存されていない結果は、完全に再現可能な結果として扱うべきではありません。

---

## 現在のリサーチ状況

現在のシステムは、以下に対応しています。

* ABCDE 日次ランキングフローの実行
* 同一日付で比較可能な 5 戦略ランキングの生成
* Top 20 の順位および元スコア表示
* ローカル過去価格キャッシュの維持
* 固定期間バックテスト
* ランダム期間バックテスト
* 年別層化ランダム検証
* QQQ とのパフォーマンス比較
* 売買回転率および最大ドローダウン計算
* 売買ライフサイクル監査
* 不完全または日付不一致の日次結果の拒否
* 機械可読な JSON および CSV 監査出力
* リサーチ設定およびランダムシードの保存

これまでの検証では、一部のランキングシグナルが年によって大きく異なる挙動を示すことも確認されています。

そのため、総合バックテスト結果が良好であるという理由だけで、戦略が安定して有効であるとは判断しません。

---

## 既知の制約

現在の公開リポジトリは、完全な機関投資家向け point-in-time リサーチプラットフォームではありません。

想定される制約は以下です。

* 過去の指数構成銘柄データが不完全
* サバイバーシップバイアスのリスク
* 上場廃止銘柄のカバレッジ不足
* ティッカー変更履歴の不足
* 財務データの公表日情報不足
* コーポレートアクション情報の不足
* ローカルデータ可用性への依存
* データベンダー間の差異
* 取引コストモデルの簡略化
* 流動性および市場インパクト仮定の限界
* 実売買検証の不足
* 一部の長期ランキングが価格ベースの代理モデルであること

価格代理による過去ランキングと、完全な point-in-time データによる再構成結果は明確に区別する必要があります。

---

## 安全性および実行ポリシー

本リポジトリは、リサーチ優先の設計を採用しています。

デフォルト設定は以下です。

```text
broker_action_allowed = False
official_adoption_allowed = False
```

リサーチ結果から、以下を自動実行してはいけません。

* 実売買注文
* 証券会社アクション
* 自動リバランス
* 正式な戦略採用
* 資金配分変更

将来的に取引実行レイヤーを追加する場合も、リサーチレイヤーから分離し、以下を必須とする設計を想定しています。

* 独立した設定
* 追加のリスク管理確認
* 明示的な手動承認
* 証券会社接続状態の確認
* ペーパートレードまたはシミュレーション検証
* 無効化可能な全体スイッチ

---

## ロードマップ

今後の主な研究・開発候補は以下です。

* より完全な point-in-time データ対応
* 過去ユニバースの再構成
* 上場廃止銘柄の対応
* 財務データの厳密な公開時刻管理
* ローリング前方検証
* Walk-forward validation
* 複数戦略アンサンブル分析
* 因子減衰分析
* 市場レジーム帰属分析
* 売買回転率制約付きポートフォリオ構築
* 取引コストストレステスト
* ペーパートレードとリサーチチェーンの分離
* PDF リサーチレポートの自動生成
* マルチエージェント型リサーチワークフロー
* シグナルライフサイクル監査の強化
* より厳格なアウト・オブ・サンプル確認検証

---

## 免責事項

本リポジトリは、以下の目的に限って提供されています。

* ソフトウェア工学研究
* 定量リサーチ
* データ分析
* 教育用途

本プロジェクトは、以下を意味するものではありません。

* 投資助言
* 金融商品の推奨
* 取引の勧誘
* 将来収益の保証
* そのまま本番運用できる実売買システム

バックテストおよびシミュレーション結果は、実際の取引結果を示すものではありません。

結果は、以下の要因による影響を受ける可能性があります。

* データ品質
* サバイバーシップバイアス
* 先読みバイアス
* データリーケージ
* 取引コスト
* 市場インパクト
* 流動性制約
* コーポレートアクション処理
* バックテストパラメータ
* データベンダー差異

本プロジェクトのコードおよびリサーチ結果の利用に伴うリスクは、利用者自身が負うものとします。

---

## プロジェクト情報

**US Tech Quant v21**

米国株式および ETF を対象とした、定量ランキング、バックテスト検証、データ監査、日次リサーチ基盤。






# US Tech Quant v21

**面向美国股票与 ETF 的研究优先型量化排名、验证与日更信号系统。**

US Tech Quant v21 是一套以 Windows、Python 和 PowerShell 为主要运行环境的量化研究系统，用于自动完成行情数据验证、特征构建、多策略评分、股票排名、历史回测、随机窗口验证、审计报告以及受保护的每日更新流程。

本项目定位为**量化研究基础设施**，而不是可以直接用于实盘交易的自动下单系统。

> **版本说明**
>
> 本项目对外公开版本名称仍然是 **US Tech Quant v21**。
>
> 仓库内部部分脚本和流水线使用了 `V22.xxx` 等更高编号。这些编号仅表示内部模块、任务和工作流的迭代版本，不代表公开版本已经升级为 v22。

---

## 项目概述

系统通过一条结构化、可审计的研究流水线，将原始市场数据转换为每日量化研究结果：

```text
市场数据
    ↓
数据完整性验证
    ↓
特征工程
    ↓
ABCDE 多策略评分
    ↓
横截面股票排名
    ↓
同日期可比性检查
    ↓
Top 20 研究结果
    ↓
历史回测与随机窗口验证
```

当前系统覆盖超过 300 只美国股票与 ETF，主要用于回答以下四个研究问题：

1. 今天每个策略排名最高的股票是什么？
2. 五个策略是否基于同一个市场交易日生成？
3. 策略信号在不同年份和不同市场环境中是否稳定？
4. 每一次排名和回测结果是否能够被重新运行、追踪和审计？

---

## 核心功能

### 每日量化研究流水线

每日流水线主要执行以下任务：

* 原始行情与复权行情更新
* 股票池完整性检查
* 缺失数据检查
* 重复 ticker-date 检查
* 特征构建
* ABCDE 五策略评分
* Top 20 排名生成
* 原始分数保存
* 五策略同日可比性验证
* JSON、CSV 和日志审计输出
* 硬性门槛判定
* 不完整结果自动拒绝

当前稳定的每日唯一入口为：

```powershell
.\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

成功运行时会返回：

```text
PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN
```

该 Guard 层用于防止日期不一致、数据缺失、子任务失败或输出不完整的结果被误认为有效研究结果。

---

## ABCDE 五策略框架

系统每天会生成五套独立评分和排名结果。

| 策略                  | 主要用途            |
| ------------------- | --------------- |
| `A1_CONTROL`        | 多因子基准控制策略       |
| `B_STATIC_MOMENTUM` | 偏重趋势与动量的策略      |
| `C`                 | 替代性因子权重组合       |
| `D`                 | 更偏分散、防御或风险约束的策略 |
| `E_R1`              | 实验性研究策略         |

每套策略都会输出：

* 信号日期
* 股票代码
* 排名
* 原始分数
* 标准化研究字段
* Top 20 汇总
* 策略级诊断信息

系统不仅保留最终排名，也保留每只股票对应的原始分数。

示例：

```text
Rank  Ticker  RawScore
1     AAPL    0.898364
2     PANW    0.884938
3     PYPL    0.883704
```

保留原始分数有助于判断排名之间的真实差距，而不是只看名次变化。

---

## 因子架构

系统当前围绕六类因子构建评分框架：

```text
基本面因子
技术面因子
策略因子
风险因子
市场环境因子
数据可信度因子
```

技术面输入可能包括：

* 相对强弱
* 动量
* RSI
* KDJ
* 布林带
* 移动平均线
* 指数移动平均线
* 成交量变化
* 波动率
* 突破强度
* 回撤特征
* 相对基准表现

最终分数由多个因子家族共同构成，而不是只依赖单一技术指标。

---

## 同日期可比性

只有当全部策略基于同一个标准市场日期生成时，系统才允许进行策略之间的横向比较。

每日 Guard 会检查以下字段：

```text
canonical_latest_date
abcde_latest_date
dram_latest_price_date
same_date_comparable_all_strategies
hard_gate_passed
```

以下情况会导致当日结果被拒绝：

* 某个策略使用了过期日期
* 行情数据尚未完整更新
* 五套策略的排名日期不一致
* 关键输出文件缺失
* 子流水线异常退出
* 数据完整性检查失败
* 股票池数量异常
* 排名结果不完整

这一机制可以避免将不同交易日生成的策略排名错误地放在一起比较。

---

## 历史验证框架

项目目前包含多种回测和验证方式。

### 固定区间回测

用于分析策略在指定历史区间内的表现。

### 随机窗口回测

从历史数据中随机抽取起始日期，以降低结果对单一回测起点的依赖。

当前支持的典型持有周期包括：

```text
20 个交易日
60 个交易日
120 个交易日
252 个交易日
504 个交易日
```

### 年度分层随机回测

在每一个自然年内分别抽取随机窗口，用于检验策略收益是否集中在少数特定年份。

### 基准比较

目前主要使用 QQQ 作为科技成长型策略的比较基准。

典型统计指标包括：

* 收益率中位数
* 相对 QQQ 的超额收益中位数
* 跑赢 QQQ 的窗口比例
* 最大回撤
* 最差窗口收益
* 换手率
* 扣除交易成本后的收益
* 不同年份的稳定性
* 不同持有周期的一致性

---

## 示例持仓规则

当前研究过的一套组合规则为：

```text
买入条件：股票进入 Top 5
卖出条件：股票跌出 Top 10
最大持仓数量：5
初始单仓权重：20%
补位来源：当前 Top 5
持仓期间再平衡：关闭
基准：QQQ
交易成本：可配置
```

这是一套用于研究和回测的配置，不代表投资建议，也不代表已经被证明能够稳定盈利。

仓库中还包含针对以下机制的测试基础设施：

* 不同买入排名阈值
* 不同卖出排名阈值
* 不同持有周期
* 不同替换规则
* 换手率限制
* 市场环境过滤
* QQQ 回退机制
* 不再平衡机制
* 交易成本压力测试

---

## 审计与研究完整性

本项目强调明确暴露失败，而不是在数据或流程异常时继续输出看似正常的结果。

系统中的审计项目包括：

* 重复 ticker-date 记录
* 缺失开盘价或收盘价
* 过期快照
* 不同策略日期不一致
* 股票池成员异常
* 非预期 ticker 删除
* 策略特定窗口删除
* 前视偏差风险
* 数据泄漏风险
* 输出文件完整性
* 冻结配置一致性
* 买卖生命周期完整性
* 强制到期退出检查
* 换手率计算检查
* 基准窗口一致性
* 随机种子记录
* 回测窗口 manifest 保存

当历史 point-in-time 数据不完整时，系统会明确标记限制，而不是将代理回测包装成严格历史重建。

---

## 快速开始

### 环境要求

* Windows 10 或 Windows 11
* PowerShell 5.1 或更高版本
* Python 3.10 或更高版本
* Git
* 本地市场数据源或兼容缓存数据

### 克隆仓库

```powershell
git clone https://github.com/kinryukii/us-tech-quant-v21.git
cd us-tech-quant-v21
```

### 创建 Python 虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

如仓库中存在依赖文件，可执行：

```powershell
pip install -r requirements.txt
```

### 临时允许 PowerShell 脚本执行

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 运行每日研究链

```powershell
.\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

### 检查 Git 状态

```powershell
git status
```

---

## 仓库结构

简化后的仓库结构如下：

```text
us-tech-quant-v21/
├─ scripts/
│  ├─ v21/
│  └─ v22/
│     ├─ 日更流水线入口
│     ├─ 排名与验证模块
│     ├─ 随机窗口回测
│     ├─ 年度稳定性诊断
│     └─ 回归测试
├─ config/
│  └─ 策略与运行配置
├─ docs/
│  └─ 方法说明与研究记录
├─ tests/
│  └─ 完整性与回归测试
└─ README.md
```

大型数据文件、运行结果、日志、虚拟环境和本地缓存不会上传到 GitHub。

常见排除内容包括：

```text
data/
outputs/
results/
.venv/
__pycache__/
*.log
*.parquet
```

---

## 数据存储建议

本项目建议将代码、市场数据和回测结果分开保存。

推荐结构：

```text
项目代码：
D:\us-tech-quant

行情与研究数据：
D:\us-tech-quant-data

回测结果与历史归档：
D:\us-tech-quant-results
```

这种结构具有以下优点：

* 减小 Git 仓库体积
* 提高提交和克隆速度
* 避免误上传大型行情数据
* 每次回测可以独立归档
* 代码、原始数据和研究输出边界更加清晰
* 便于清理旧结果而不影响核心代码

---

## 可复现性

为了确保研究结果可复现，每次运行都应保存以下信息：

* 策略配置
* 股票池定义
* 信号日期
* 行情日期
* 随机种子
* 交易成本假设
* 基准序列
* 测试窗口清单
* 汇总 JSON
* 排名 CSV
* 数据完整性诊断
* 代码版本或 Git commit

随机回测必须明确记录随机种子。

示例：

```text
MASTER_SEED=2026071604
```

如果一项结果没有对应的配置、股票池、时间范围、数据版本和随机种子，就不应被视为完全可复现。

---

## 当前研究状态

当前系统已经能够：

* 运行 ABCDE 每日排名流程
* 输出五套同日期可比的策略排名
* 打印 Top 20 股票排名与原始分数
* 维护本地历史行情缓存
* 执行固定区间回测
* 执行随机窗口回测
* 执行年度分层随机验证
* 与 QQQ 进行比较
* 计算换手率和最大回撤
* 检查交易生命周期
* 拒绝不完整或日期不一致的日更结果
* 输出机器可读的 JSON 和 CSV 审计文件
* 保留研究配置和随机种子

现有研究也表明，某些排名信号在不同年份中的表现差异较大。

因此，本项目不会因为某个总体回测结果较好，就直接认定策略已经稳定有效。

---

## 已知限制

当前公开仓库仍不应被视为完整的机构级 point-in-time 量化研究平台。

已知限制可能包括：

* 历史指数成分数据不完整
* 存续偏差风险
* 退市股票覆盖不足
* 历史代码变更信息不完整
* 历史财务数据发布日期不完整
* 公司行动元数据不完整
* 对本地数据可用性的依赖
* 不同数据供应商之间存在差异
* 交易成本模型相对简化
* 流动性和市场冲击假设有限
* 实盘执行验证不足
* 部分长期排名基于价格代理模型

历史代理排名和严格 point-in-time 重建结果必须明确区分。

---

## 安全与执行策略

本仓库默认采用研究优先原则。

默认状态为：

```text
broker_action_allowed = False
official_adoption_allowed = False
```

研究结果不得自动触发：

* 实盘订单
* 券商操作
* 自动调仓
* 正式策略采纳
* 资金分配变更

未来如增加交易执行层，也应继续与研究层隔离，并要求：

* 独立配置
* 额外风控检查
* 明确人工批准
* 券商连接状态验证
* 模拟盘或纸面交易验证
* 可关闭的总开关

---

## 研究路线图

后续研究方向包括：

* 更完整的 point-in-time 数据支持
* 历史股票池重建
* 退市股票覆盖
* 更严格的基本面数据时间戳
* 滚动前向验证
* Walk-forward validation
* 多策略组合分析
* 因子衰减分析
* 市场环境归因
* 换手率约束组合构建
* 交易成本压力测试
* 模拟盘与研究链隔离
* 自动生成 PDF 研究报告
* 多 Agent 量化研究工作流
* 更完整的信号生命周期审计
* 更严格的样本外确认性测试

---

## 免责声明

本仓库仅用于：

* 软件工程研究
* 量化研究
* 数据分析
* 教育用途

本项目不构成：

* 投资建议
* 证券推荐
* 交易邀请
* 收益保证
* 可直接部署的生产级实盘系统

历史回测和模拟结果不代表真实交易收益。

研究结果可能受到以下因素影响：

* 数据质量
* 存续偏差
* 前视偏差
* 数据泄漏
* 交易成本
* 市场冲击
* 流动性约束
* 公司行动处理
* 回测参数选择
* 数据供应商差异

使用本项目代码和研究结果所产生的风险由使用者自行承担。

---

## 项目信息

**US Tech Quant v21**

面向美国股票和 ETF 的量化排名、回测验证、数据审计与每日研究基础设施。


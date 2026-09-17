# A2 Attribution Framework R1

## Scope

A2 Attribution Framework R1 explains realized portfolio economic contribution. It does not explain model features and does not estimate a Barra-style risk model.

- **Portfolio attribution:** where realized gross, cost, and net contribution occurred across securities, time, rank buckets, and groups. This is R1.
- **Model explanation:** how predictions mechanically depend on features, such as SHAP or split gain. This is outside R1.
- **Factor attribution:** decomposition against defined factor returns or exposures. This is outside R1.
- **Risk attribution:** decomposition of variance or covariance risk. This is outside R1.

> R1 explains realized economic contribution, not causal feature importance.

Attribution is diagnostic. Attribution does not authorize model modification, parameter tuning, factor selection, promotion, or use of 2026 outcomes for research selection.

## Input schema

`AttributionRow` field roles are machine-readable through `schema_contract()`.

Required identity fields are `strategy_id`, `date`, `security_id`, `component_type`, `model_id`, `universe_id`, and `vintage_id`. A realized `net_contribution` or authoritative `portfolio_contribution` is conditionally required. Rows without either are rejected unless the configuration explicitly authorizes `portfolio_weight * security_return`; that authorization is disabled by default.

Optional fields include ticker, sector, industry, rank, weights, raw security return, transaction cost, turnover contribution, gross/net/cost contribution, NAV, fold, and regime. Missing sector or industry becomes `UNKNOWN`; it is never inferred from ticker or an external service. Missing economic fields remain unavailable rather than becoming zero.

`component_type` is one of:

- `SECURITY`
- `CASH`
- `COST`
- `OTHER_EXPLICIT_RESIDUAL`

Cash, cost, slippage, rounding, or another residual must use an explicit row. Residual contribution is never reassigned to a security.

## Contribution convention

R1 uses signed return contributions:

```text
net_contribution = gross_contribution + cost_contribution
cost_contribution <= 0 for a cost drag
transaction_cost >= 0 for the corresponding unsigned charge
```

For each date:

```text
sum(all explicit row net contributions)
= authoritative portfolio net return
```

The same identity is checked for authoritative gross return and cost when those fields exist. NAV returns are also checked when both `nav_before` and `nav_after` exist.

Summing daily return contributions is an additive accounting diagnostic. It is not silently represented as a compounded cumulative NAV return. A future caller that needs an exact cumulative-return decomposition must supply an explicitly defined linking convention.

An authoritative realized execution contribution takes precedence. Raw security return and `weight * return` are not substitutes unless the immutable input contract explicitly authorizes derived contribution.

## Reconciliation

The configured accounting tolerance defaults to `1e-12`; it is a numeric identity tolerance, not a scientific performance threshold. A report fails if any of the following occurs:

- a row date and authoritative daily date do not align;
- net security/component contribution does not sum to the authoritative daily return;
- row `gross + cost != net`;
- authoritative gross or cost identities differ;
- signed cost contribution disagrees with the unsigned transaction charge;
- NAV-implied return disagrees with the authoritative return;
- strategy identity differs.

Tables may be inspected after a failed reconciliation, but they cannot be called verified. The full immutable runner refuses to write final outputs unless A, A2, and incremental identities all pass.

## Attribution dimensions

Security attribution ranks cumulative portfolio contribution, never raw stock return. It reports gross/net/cost, holding days, entry observations when prior weights are available, average/max weight, positive/negative days, and positive/negative contribution shares.

Time attribution supports year, quarter, month, and optional supplied fold/regime fields. Rank buckets default to 1–5, 6–10, and 11–20 and are configurable with overlap validation. Non-security components and unranked rows receive explicit buckets so the additive identity is preserved.

Sector and industry attribution use only supplied metadata. `UNKNOWN` is a visible group, not a passing lineage claim.

Winner/loser classification defaults to strict arithmetic sign of cumulative net security contribution. A nonzero threshold must be caller-configured; R1 assigns no economic meaning to it.

## Concentration metrics

Positive and negative contribution mass are treated separately. For nonnegative shares `s_i`, R1 reports:

```text
HHI = sum(s_i ^ 2)
effective contributor count = 1 / HHI
```

Signed contributions are never inserted directly into HHI. Security top-1/5/10 shares and period top-1/2/3 shares are reported. No concentration threshold is preregistered in R1, so status is `INFORMATIONAL_ONLY`; a large share is not automatically labeled dangerous or unstable.

## A versus A2

`IncrementalAttributionEngine` outer-aligns rows on date, security, and component type. It reports:

```text
incremental realized contribution = A2 net contribution - A net contribution
incremental cost = A2 cost contribution - A cost contribution
incremental turnover = A2 turnover contribution - A turnover contribution
```

Taxonomy includes `A2_ONLY_SELECTION`, `A_ONLY_SELECTION`, `COMMON_SECURITY_WEIGHT_DIFFERENCE`, `COMMON_SECURITY_SAME_OR_NEAR_WEIGHT`, `COMMON_SECURITY_WEIGHT_UNKNOWN`, and explicit non-security component differences. The broader position class retains `A2_ONLY`, `A_ONLY`, `DIFFERENT_WEIGHT`, and `COMMON_POSITION`.

This is incremental realized contribution. It is not automatically model skill, factor alpha, or a causal estimate. A and A2 must independently reconcile, share the required date window and universe identity, and satisfy:

```text
sum(A2 row contribution - A row contribution)
= A2 authoritative portfolio contribution - A authoritative portfolio contribution
```

## Drawdown diagnostics

R1 detects peak-to-trough NAV episodes deterministically. Recovery is the first observation with NAV strictly greater than the prior peak. For each episode it sums rows in `peak_date < date <= trough_date` by security, sector, and rank bucket.

> Contribution during a drawdown window is not a unique causal decomposition of maximum drawdown.

R1 intentionally does not implement path-dependent Shapley attribution or claim that the arithmetic contribution sum equals the compounded percentage drawdown.

## Immutable full-run contract

The full runner requires a frozen manifest, exact paths, SHA-256 for every normalized input, the authoritative freeze ID `A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1`, strategy/model identities, exact date coverage, training cutoff, universe identity, data-manifest hash, and model hash metadata. Names containing `latest` or `.tmp`, and paths under the currently protected Overnight run ID, fail closed.

Outputs are written once to a new directory under `D:\us-tech-quant-results`; an existing output directory is never overwritten. Supported output tables are the standard summary, security, time, rank bucket, group, drawdown-window, incremental, and reconciliation artifacts.

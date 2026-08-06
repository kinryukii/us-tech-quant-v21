# FAST3 R25 asymmetric direction with abstention

R25 is a single predeclared hypothesis: `ASYMMETRIC_DIRECTION_WITH_ABSTENTION`.
It preserves R24's 20 ordered features, interaction transforms, `HistGradientBoostingClassifier`
parameters, deterministic seed, event/actionability head, 60-day/65-day schedule, 24-hour
purge and embargo, top-five-percent actionability and costs.

The conditional direction model is changed only by fitting independent `P(UP_FIRST | event)`
and `P(DOWN_FIRST | event)` heads.  A direction is emitted only for the immutable candidate
set `(confidence, margin)`: `(0.55, 0.05)`, `(0.55, 0.10)`, `(0.60, 0.05)`, `(0.60, 0.10)`.
All other rows are `ABSTAIN`.

D1/D2 select one candidate and persist a content-hashed candidate freeze before D3/D4 is
scored.  Confirmation can open holdout only when it preserves all R24 gates and the added R25
gain and direction-expectancy conditions.  A failed confirmation is a normal negative result
and must not read H1--H4.

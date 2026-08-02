# FAST3-005 implementation report

Status: `IMPLEMENTATION_VALIDATED_SYNTHETIC_ONLY`.

FAST3-005 adds a pre-registered abstention layer for low Opportunity score, low
Direction confidence, model disagreement, data-trust failure, and non-positive
cost-aware expected return at both 10bps and 20bps. The 0.60 Opportunity gate is
inherited unchanged from FAST3-004 and was not optimized.

Only synthetic decision rows are permitted for this checkpoint. No real
Development run, frozen Validation run, Confirmation read, final model training,
broker action, order, position, predictive conclusion, or economic conclusion
has occurred.

Python compilation passed and nine focused unit tests passed. The synthetic
smoke covered each of the six abstention codes plus one eligible signal: six of
seven decisions abstained, while all seven emitted zero proposed positions and
zero orders. This proves only deterministic control flow, not predictive or
economic validity.

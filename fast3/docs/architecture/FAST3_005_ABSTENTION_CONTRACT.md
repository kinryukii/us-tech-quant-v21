# FAST3-005 abstention contract

FAST3-005 is a deterministic decision layer over FAST3-004 fold-local scores. It
does not alter FAST3-004's pre-registered Opportunity threshold of 0.60, any
model, feature, seed, split, or FAST3-002 executable contract.

The frozen priority order is: data trust; Opportunity below 0.60; Direction
confidence below 0.60; model disagreement above 0.20; non-positive expected
net return at 10bps; non-positive expected net return at 20bps. The first
matching reason is emitted as the explicit abstention code.

Every abstention emits `ABSTAIN`, no candidate direction, zero proposed
positions, and zero orders. A non-abstaining record is only eligible for later
FAST3-002 portfolio evaluation; it is never an order or an opened position.

Expected net returns supplied to a future empirical run must derive from the
unchanged FAST3-002 executable label, exit, and 10/20bps cost surfaces. This
implementation has not read Development, frozen Validation, or Confirmation.

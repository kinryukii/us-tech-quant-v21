# FAST3 V22.085 Authorization and Hard Contract

Stage: `V22.085_FAST3_AGGRESSIVE_BOUNDED_SEARCH_ENGINE_R1`

The user authorizes autonomous local research development within:
- Repository: `D:\us-tech-quant`
- Data: `D:\us-tech-quant-data`
- Results: `D:\us-tech-quant-results\fast3_v22_085_aggressive_bounded_search`

Authorized actions: read existing code/data/results, modify repository research code,
create bounded stage artifacts, run tests, train models, execute historical research
backtests, checkpoint, resume, and remove non-winning V22.085 model binaries.

Not authorized: deleting canonical data, overwriting frozen V22.081-V22.084 results,
placing broker orders, enabling live execution, claiming unrun results, or repeatedly
opening consumed holdouts.

## Aggressive search budget
- Up to 8 generations
- Up to 40 registered candidates per generation
- Up to 320 registered Development candidates
- Up to 3 model families
- Up to 24 active features
- Up to 3 active candidates
- Up to 4 saved model files
- Label horizons limited to 30/60/120/180 minutes

Ordinary no-improvement may not terminate the stage before at least four legal
generations and 120 registered Development candidates. Earlier termination is legal
only for fatal leakage/data failure, insufficient untouched history/statistical-power
impossibility, untouched fold exhaustion, safe stop, or usage limit.

## Holdout contract
All chronological folds and hashes are frozen before training. Development/Internal
OOS may support optimization. Generation Validation, Confirmation, and Global Final
Holdout are one-read resources. All consumed V22.081-V22.084 periods lose unseen
status permanently. Purge and embargo are mandatory.

## Research architecture
SOXL-long and SOXS-long are modeled separately. A one-sided strategy is legal.
Opportunity is a hard gate; side probability and Entry quality form final confidence.
Top-K is bounded and may only rank signals above an absolute floor. NO_TRADE remains
valid. No more than one new entry per side and two total per day.

## Robustness contract
Candidate selection prioritizes 1/3/5-minute delay worst-case result, 20bps OOS net,
chronological fold consistency, statistical power, drawdown, concentration, and
stability. Training return is not an improvement criterion. No future leakage,
forced trades, or post-hoc regime selection.

## Filesystem contract
One main engine and one stage directory. No V22.085A/B/C, no per-experiment folders,
no unlimited backups/reports. Save only champion, second, third, and baseline model.
All other candidates remain registry records only.

## Permissions
`broker_action_allowed=false`
`official_adoption_allowed=false`

Paper/shadow may become true only after all frozen research gates and the one-time
Global Final Holdout pass. This authorization never enables real trading.

# FAST3 R4 Two-Stage Direction — Hard Storage R2.2

R4 is a fixed historical architecture comparison, not a strategy search and not prospective validation. It compares only the frozen R3-style three-class `hgb_leaf7` model with a fixed two-stage `EVENT/NO_EVENT` then `UP_FIRST/DOWN_FIRST` `hgb_leaf7` model.

The runner reads the external R3 freeze, validates the R3 STOP decision and post-audit evidence, and uses the exact ordered 20 features plus the three frozen interactions. `AMBIGUOUS` rows are excluded. The only supervised outcome is the 24-hour path label; feature-availability timestamps are rejected when later than the decision time.

All eight 60-day blocks are deterministically selected and frozen before fitting: four development blocks with three seeds, then four non-prospective internal-holdout blocks with five seeds. Training is expanding-only and ends at least 24 hours of purge plus 24 hours of embargo before each test block. Imputation is fitted only on each training fold. Fold weights are `uniqueness_weight × training-fold class_weight × training-fold era_weight`; test rows retain their natural distribution.

Development failure stops before internal holdout. Per block/seed checkpoints resume only if their complete fixed fingerprint matches. Repeated seeds are summarized within blocks and all uncertainty is block-clustered. A successful holdout freezes exactly one two-stage model for future blind research-shadow scoring; it has no broker, paper-order, or live-order capability.

Every artifact and checkpoint is written only beneath caller-supplied external frozen/scratch roots. No repository-relative output or `.local_results` fallback exists.

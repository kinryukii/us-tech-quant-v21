# FAST3-002 nested purged walk-forward contract

All FAST3-002 selection is Development-only. The outer fold is a chronological
future simulation: its test rows never choose model, feature, calibration, or
threshold. Inner folds are generated only from that outer training span.

The frozen purge is 1,440 minutes and the frozen embargo is 1,440 minutes. A
training event is excluded if its declared `label_end_timestamp_et` reaches the
outer test start minus embargo; absent a declared end, the maximum 24-hour label
window is assumed. This removes paths shared by adjacent 24-hour labels and
their ETF/underlying mappings. Scalers are fit exclusively on the train fold.

The splitter rejects Confirmation timestamps and explicit `CONFIRM*` split rows.
FAST3-002 provides splitter/test infrastructure only; it does not fit, rank, or
select a model.

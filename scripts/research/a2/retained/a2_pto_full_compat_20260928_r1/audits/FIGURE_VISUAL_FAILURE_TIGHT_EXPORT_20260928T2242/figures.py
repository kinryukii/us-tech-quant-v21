"""Complete registered-account visualizations and descriptive paired effects.

Run only after analyze.py has completed all 22,176 registered year/strategy rows.
No training, strategy generation, selection, tuning, or statistical causal claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
from common import ROOT, MEMBERS, BUNDLES, FUSIONS, RISKS, OPTIMIZERS, AXES, registry, sha, write_json, pd, np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.colors import TwoSlopeNorm

OUT = ROOT / "analysis"
FIGURES = OUT / "figures"
METRICS = ["indicative_return", "indicative_max_drawdown", "mean_gross_exposure", "mean_cash", "fees", "half_turnover", "uncertified_days"]
INTERACTION_METRICS = ["indicative_return", "indicative_max_drawdown", "mean_gross_exposure", "fees"]
ZERO_TOLERANCE = 1e-12
YEARS = [2025, 2026]
YEAR_LABELS = {2025: "2025 pre-2026 available-context diagnostic", 2026: "2026 Jan-Sep qualified-subpool diagnostic"}
PROVENANCE_NOTE = "2026 was previously observed; formal full-pool performance is BLOCKED_DATA. These are descriptive account comparisons."
SOURCES = {}


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def read_csv(name):
    path = OUT / name
    require(path.exists(), "REQUIRED_COMPLETE_ANALYSIS_FILE_MISSING:" + name)
    SOURCES[str(path.relative_to(ROOT))] = sha(path)
    return pd.read_csv(path)


def keys(frame):
    return set(zip(frame.year.astype(int), frame.strategy.astype(str)))


def validate_complete_tables(receipt, table, coverage):
    expected = {(year, path["strategy"]) for year in YEARS for path in registry()[1]}
    require(receipt.get("complete") is True and receipt.get("rows") == receipt.get("expected_rows") == len(expected) == 22176,
            "REFUSE_INCOMPLETE_MAIN_ANALYSIS_RECEIPT")
    for name, frame in [("results", table), ("coverage", coverage)]:
        require(len(frame) == len(expected) and not frame.duplicated(["year", "strategy"]).any(), "INCOMPLETE_OR_DUPLICATED_" + name.upper())
        require(keys(frame) == expected, "REGISTERED_YEAR_STRATEGY_KEYS_CHANGED:" + name)
    require(not coverage.status.eq("NOT_EXECUTED").any(), "REGISTERED_ACCOUNT_NOT_EXECUTED")
    require(set(METRICS).issubset(table.columns), "REQUIRED_METRICS_MISSING")
    require(table.loc[table.year.eq(2026), "research_status"].eq("OBSERVED_HISTORY_QUALIFIED_SUBPOOL_DIAGNOSTIC").all(), "2026_DIAGNOSTIC_LABEL_MISSING")
    require(not table.certified_shareholder_total_return.fillna(True).any(), "UNCERTIFIED_RETURN_MISLABELED")
    require(not table.selected_for_deployment.fillna(True).any(), "RESULTS_HAVE_BEEN_SELECTED")
    require(receipt.get("selection_or_retraining_calls") == 0 and receipt.get("formal_2026_full_pool_status") == "BLOCKED_DATA", "ANALYSIS_BOUNDARY_CHANGED")
    registered = pd.DataFrame(registry()[1])
    registered["members"] = registered.members.map(lambda value: "|".join(value))
    dimensions = ["stream", "bundle", "fusion", "risk", "optimizer", "axis", "target_fusion", "members"]
    joined = table.merge(registered[["strategy"] + dimensions], on="strategy", validate="many_to_one", suffixes=("", "_registered"))
    for dimension in dimensions:
        require(joined[dimension].astype(str).eq(joined[dimension + "_registered"].astype(str)).all(), "REGISTERED_DIMENSION_CHANGED:" + dimension)


def load_complete():
    receipt_path = OUT / "ANALYSIS_RECEIPT.json"
    require(receipt_path.exists(), "REFUSE_INCOMPLETE_MAIN_ANALYSIS_NO_RECEIPT")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("complete") is True and receipt.get("rows") == 22176, "REFUSE_INCOMPLETE_MAIN_ANALYSIS_RECEIPT")
    SOURCES[str(receipt_path.relative_to(ROOT))] = sha(receipt_path)
    table = read_csv("ALL_POSITIVE_NEGATIVE_RESULTS.csv")
    coverage = read_csv("COMBINATION_COVERAGE.csv")
    validate_complete_tables(receipt, table, coverage)
    return receipt, table, coverage


def statistics(values):
    original = np.asarray(values, dtype=float)
    valid = original[np.isfinite(original)]
    result = {"total_pairs": len(original), "finite_pairs": len(valid), "missing_pairs": len(original)-len(valid)}
    if not len(valid):
        result.update({key: None for key in ["median_delta", "mean_delta", "q25_delta", "q75_delta", "positive_fraction", "negative_fraction", "tie_fraction"]})
        return result
    result.update(median_delta=float(np.median(valid)), mean_delta=float(np.mean(valid)), q25_delta=float(np.quantile(valid, .25)),
                  q75_delta=float(np.quantile(valid, .75)), positive_fraction=float(np.mean(valid > ZERO_TOLERANCE)),
                  negative_fraction=float(np.mean(valid < -ZERO_TOLERANCE)), tie_fraction=float(np.mean(np.abs(valid) <= ZERO_TOLERANCE)))
    return result


def json_scalar(value):
    return value.item() if isinstance(value, np.generic) else value


def summarize(frame, group_columns, prefix="delta_", metric_names=METRICS):
    records = []
    for values, group in frame.groupby(group_columns, sort=False, dropna=False):
        if not isinstance(values, tuple):
            values = (values,)
        row = {key: json_scalar(value) for key, value in zip(group_columns, values)}
        row["metrics"] = {metric: statistics(group[prefix + metric].to_numpy(float)) for metric in metric_names}
        row["return_win_fraction"] = row["metrics"]["indicative_return"]["positive_fraction"]
        row["return_negative_fraction"] = row["metrics"]["indicative_return"]["negative_fraction"]
        records.append(row)
    return records


def check_contrast(frame, expected, dimensions):
    require(len(frame) == len(expected) and keys(frame) == keys(expected), "INCOMPLETE_PAIRED_CONTRAST")
    require(not frame.duplicated(["year", "strategy"]).any(), "DUPLICATED_PAIRED_CONTRAST")
    require(set("delta_" + metric for metric in METRICS).issubset(frame.columns), "INCOMPLETE_PAIRED_METRICS")
    for metric in METRICS:
        actual = frame[metric].to_numpy(float)-frame["reference_" + metric].to_numpy(float)
        recorded = frame["delta_" + metric].to_numpy(float)
        finite = np.isfinite(actual) & np.isfinite(recorded)
        require(np.array_equal(np.isnan(actual), np.isnan(recorded)), "PAIRED_METRIC_MISSINGNESS_CHANGED:" + metric)
        scale = np.abs(frame[metric].to_numpy(float))+np.abs(frame["reference_" + metric].to_numpy(float))+1.
        tolerance = 8*np.finfo(float).eps*scale+1e-12
        require((np.abs(recorded[finite]-actual[finite]) <= tolerance[finite]).all(), "PAIRED_METRIC_ARITHMETIC_CHANGED:" + metric)
    require(set(dimensions).issubset(frame.columns), "PAIRED_DIMENSIONS_MISSING")


def conditional_fusion_interactions(contrast):
    base_risk = contrast.loc[contrast.risk.eq("diagonal"), ["year", "axis", "bundle", "fusion", "optimizer"] + ["delta_" + metric for metric in INTERACTION_METRICS]]
    base_opt = contrast.loc[contrast.optimizer.eq("mean_variance"), ["year", "axis", "bundle", "fusion", "risk"] + ["delta_" + metric for metric in INTERACTION_METRICS]]
    merged = contrast.merge(base_risk, on=["year", "axis", "bundle", "fusion", "optimizer"], validate="many_to_one", suffixes=("", "_diag"))
    merged = merged.merge(base_opt, on=["year", "axis", "bundle", "fusion", "risk"], validate="many_to_one", suffixes=("", "_mv"))
    corner = contrast.loc[contrast.risk.eq("diagonal") & contrast.optimizer.eq("mean_variance"), ["year", "axis", "bundle", "fusion"] + ["delta_" + metric for metric in INTERACTION_METRICS]]
    corner = corner.rename(columns={"delta_" + metric: "delta_" + metric + "_corner" for metric in INTERACTION_METRICS})
    merged = merged.merge(corner, on=["year", "axis", "bundle", "fusion"], validate="many_to_one")
    for metric in INTERACTION_METRICS:
        prefix = "delta_" + metric
        merged["fusion_x_risk__" + metric] = merged[prefix]-merged[prefix + "_diag"]
        merged["fusion_x_optimizer__" + metric] = merged[prefix]-merged[prefix + "_mv"]
        merged["fusion_x_risk_x_optimizer__" + metric] = merged[prefix]-merged[prefix + "_diag"]-merged[prefix + "_mv"]+merged[prefix + "_corner"]
    return merged


def configure():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
                         "xtick.labelsize": 8, "ytick.labelsize": 8, "figure.dpi": 110, "savefig.dpi": 180,
                         "pdf.fonttype": 42, "ps.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False})


def check_layout(fig, name):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bounds = fig.bbox
    drawn_text = list(fig.texts)
    for legend in fig.legends:
        drawn_text.extend(legend.get_texts())
    for axes in fig.axes:
        drawn_text.extend([axes.title, axes.xaxis.label, axes.yaxis.label])
        drawn_text.extend(axes.texts)
        for axis in [axes.xaxis, axes.yaxis]:
            low, high = sorted(axis.get_view_interval())
            for tick in axis.get_major_ticks()+axis.get_minor_ticks():
                if low-1e-12 <= tick.get_loc() <= high+1e-12:
                    drawn_text.extend([tick.label1, tick.label2])
            drawn_text.append(axis.get_offset_text())
    for artist in drawn_text:
        if not artist.get_visible() or not artist.get_text():
            continue
        box = artist.get_window_extent(renderer)
        require(box.x0 >= bounds.x0-1 and box.y0 >= bounds.y0-1 and box.x1 <= bounds.x1+1 and box.y1 <= bounds.y1+1,
                "PLOT_TEXT_CLIPPED:" + name + ":" + artist.get_text())
    if fig._suptitle is not None:
        global_box = fig._suptitle.get_window_extent(renderer)
        for ax in fig.axes:
            if ax.title.get_text():
                panel_box = ax.title.get_window_extent(renderer)
                require(global_box.y0 >= panel_box.y1+5, "GLOBAL_PANEL_TITLE_OVERLAP:" + name)
    for ax in fig.axes:
        for artist in ax.texts:
            if not (artist.get_gid() or "").startswith("heat_cell_"):
                continue
            j, i = artist.get_position()
            corners = ax.transData.transform([[j-.5, i-.5], [j+.5, i+.5]])
            left, right = sorted(corners[:, 0])
            low, high = sorted(corners[:, 1])
            box = artist.get_window_extent(renderer)
            require(box.x0 >= left+1 and box.x1 <= right-1 and box.y0 >= low+1 and box.y1 <= high-1,
                    "HEATMAP_ANNOTATION_EXCEEDS_OWN_CELL:" + name + ":" + artist.get_text())


def panel_canvas(fig, bottom):
    # Constrained-layout rect is (left, bottom, width, height), not upper bounds.
    # Reserve a separate top band so global and panel titles cannot intersect.
    fig.get_layout_engine().set(rect=(0, bottom, 1, .90-bottom))


def global_title(fig, text, fontsize):
    artist = fig.suptitle(text, fontsize=fontsize, y=.987)
    artist.set_in_layout(False)


def fee_annotation(value):
    if not np.isfinite(value):
        return "NA"
    if value == 0:
        return "0"
    return f"{value/1000:+.3g}k" if abs(value) >= 1000 else f"{value:+.3g}"


def save_figure(fig, name, outputs):
    check_layout(fig, name)
    for suffix in ["png", "pdf"]:
        path = FIGURES / f"{name}.{suffix}"
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        outputs[str(path.relative_to(ROOT))] = sha(path)
    plt.close(fig)


def scatter_accounts(table, outputs):
    colors = {"singleton": "#4c78a8", "linear": "#f58518", "trees": "#54a24b", "neural": "#e45756", "all_interfaces": "#b279a2", "point13": "#222222"}
    labels = {"singleton": "31 single predictors", "linear": "Linear-3 cooperation", "trees": "Tree/additive-7 cooperation", "neural": "Neural-3 cooperation", "all_interfaces": "All-31 interface cooperation", "point13": "13-expert target fusion"}
    fig, axes = plt.subplots(2, 4, figsize=(17, 8.5), sharex=True, sharey=True, layout="constrained")
    panel_canvas(fig, .135)
    for row, year in enumerate(YEARS):
        for column, axis in enumerate(AXES):
            ax = axes[row, column]
            group = table.loc[table.year.eq(year) & table.axis.eq(axis)]
            count = 0
            for bundle, color in colors.items():
                part = group.loc[group.bundle.eq(bundle)]
                finite = np.isfinite(part.mean_gross_exposure) & np.isfinite(part.indicative_return)
                count += int(finite.sum())
                ax.scatter(100*part.loc[finite, "mean_gross_exposure"], 100*part.loc[finite, "indicative_return"],
                           s=8 if bundle != "point13" else 15, color=color, alpha=.35, linewidths=0, rasterized=True)
            ax.axhline(0, color="0.65", lw=.65, zorder=0)
            ax.grid(alpha=.15)
            ax.set_title(f"{year} | {axis} | {count:,}/{len(group):,} finite accounts")
            if row == 1:
                ax.set_xlabel("Mean actual gross exposure (%)")
            if column == 0:
                ax.set_ylabel(f"{YEAR_LABELS[year]}\nIndicative account return (%)")
    handles = [Line2D([], [], color=color, marker="o", linestyle="", markersize=5, label=labels[bundle]) for bundle, color in colors.items()]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.5, .038), ncol=3, frameon=False, fontsize=8)
    global_title(fig, "All registered independent accounts: return and actual exposure", 14)
    fig.text(.5, .014, PROVENANCE_NOTE, ha="center", fontsize=8)
    save_figure(fig, "all_axes_return_actual_exposure", outputs)


def heatmap(ax, matrix, row_labels, column_labels, title, unit, fee_labels=False):
    values = np.asarray(matrix, dtype=float)
    finite = np.isfinite(values)
    maximum = float(np.max(np.abs(values[finite]))) if finite.any() else 0.
    maximum = max(maximum, 1e-8)
    image = ax.imshow(np.ma.masked_invalid(values), cmap="RdBu_r", norm=TwoSlopeNorm(vmin=-maximum, vcenter=0, vmax=maximum), aspect="auto")
    ax.set_xticks(range(len(column_labels)), column_labels, rotation=30, ha="right")
    ax.set_yticks(range(len(row_labels)), row_labels)
    ax.set_title(title)
    ax.tick_params(length=0)
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            value = values[i, j]
            text = fee_annotation(value) if fee_labels else "NA" if not np.isfinite(value) else f"{value:+.2f}" if abs(value) >= .005 else "0.00"
            color = "white" if np.isfinite(value) and abs(value) > .65*maximum else "black"
            artist = ax.text(j, i, text, ha="center", va="center", fontsize=7.5, color=color)
            artist.set_gid(f"heat_cell_{i}_{j}")
    colorbar = ax.figure.colorbar(image, ax=ax, shrink=.75, pad=.03)
    # Exact in-range ticks avoid a floating-point undershoot of TwoSlopeNorm
    # producing an infinite colorbar transform at the lower endpoint.
    colorbar.set_ticks(np.linspace(-maximum, maximum, 5))
    colorbar.set_label(unit, fontsize=8)


def median_matrix(frame, rows, columns, row_name, column_name, metric, multiplier=1.):
    grid = frame.groupby([row_name, column_name], sort=False)[metric].median().unstack(column_name)
    return grid.reindex(index=rows, columns=columns).to_numpy(float)*multiplier


def fusion_heatmaps(fusion, outputs):
    panels = [("indicative_return", "Median return difference", "percentage points", 100.),
              ("indicative_max_drawdown", "Median max-drawdown difference", "pp; positive = shallower", 100.),
              ("mean_gross_exposure", "Median actual-exposure difference", "percentage points", 100.),
              ("fees", "Median total-fee difference", "USD; positive = more cost", 1.)]
    for year in YEARS:
        for axis in AXES:
            part = fusion.loc[fusion.year.eq(year) & fusion.axis.eq(axis)]
            fig, axes = plt.subplots(1, 4, figsize=(17, 7), layout="constrained")
            panel_canvas(fig, .145)
            for ax, (metric, title, unit, multiplier) in zip(axes, panels):
                matrix = median_matrix(part, FUSIONS, list(BUNDLES), "fusion", "bundle", "delta_" + metric, multiplier)
                heatmap(ax, matrix, FUSIONS, list(BUNDLES), title, unit, fee_labels=metric == "fees")
            global_title(fig, f"{YEAR_LABELS[year]} | {axis}: cooperation vs equal fusion within the same members", 12)
            fig.text(.5, .064, "All 11 fusion methods and four fixed bundles; median of 36 same-risk/optimizer account contrasts per cell.", ha="center", fontsize=8)
            fig.text(.5, .040, "Fee cell labels: three significant digits; k = 1,000 USD. Unrounded statistical values remain in the CSV tables.", ha="center", fontsize=7.5)
            fig.text(.5, .016, PROVENANCE_NOTE, ha="center", fontsize=7.5)
            save_figure(fig, f"fusion_effects_{year}_{axis}", outputs)


def risk_optimizer_heatmaps(risk, interactions, outputs):
    core_risk = risk.loc[risk.target_fusion.eq("none")]
    panels = [(core_risk, "delta_indicative_return", "Risk effect vs diagonal", "return percentage points", 100.),
              (core_risk, "delta_mean_gross_exposure", "Risk effect vs diagonal", "actual-exposure percentage points", 100.),
              (interactions, "risk_x_optimizer__indicative_return", "Risk x optimizer interaction", "return percentage points", 100.),
              (interactions, "risk_x_optimizer__indicative_max_drawdown", "Risk x optimizer interaction", "drawdown pp; positive = shallower", 100.)]
    for year in YEARS:
        for axis in AXES:
            fig, axes = plt.subplots(1, 4, figsize=(17, 7.5), layout="constrained")
            panel_canvas(fig, .145)
            for ax, (source, metric, title, unit, multiplier) in zip(axes, panels):
                part = source.loc[source.year.eq(year) & source.axis.eq(axis)]
                matrix = median_matrix(part, RISKS, OPTIMIZERS, "risk", "optimizer", metric, multiplier)
                heatmap(ax, matrix, RISKS, OPTIMIZERS, title, unit)
            global_title(fig, f"{YEAR_LABELS[year]} | {axis}: all 12 risk and three optimization methods", 12)
            fig.text(.5, .051, "Each cell aggregates 75 prediction streams. Interaction = (risk,opt) - (risk,MV) - (diagonal,opt) + (diagonal,MV).", ha="center", fontsize=8)
            fig.text(.5, .030, "Same registered components; independently advancing holdings. A positive return difference is not proof of learning or causality.", ha="center", fontsize=8)
            fig.text(.5, .010, PROVENANCE_NOTE, ha="center", fontsize=7.5)
            save_figure(fig, f"risk_optimizer_effects_interactions_{year}_{axis}", outputs)


def main():
    receipt, table, coverage = load_complete()
    core = table.loc[table.target_fusion.eq("none")]
    specifications = {
        "prediction_stream": ("PREDICTOR_PAIRED_CONTRASTS.csv", core, ["year", "axis", "stream"], "ridge"),
        "fusion": ("FUSION_PAIRED_CONTRASTS.csv", core.loc[core.bundle.ne("singleton")], ["year", "axis", "bundle", "fusion"], "equal within identical bundle"),
        "risk": ("RISK_PAIRED_CONTRASTS.csv", table, ["year", "axis", "risk"], "diagonal"),
        "optimizer": ("OPTIMIZER_PAIRED_CONTRASTS.csv", table, ["year", "axis", "optimizer"], "mean_variance"),
        "target_fusion": ("TARGET_FUSION_PAIRED_CONTRASTS.csv", table.loc[table.target_fusion.ne("none")], ["year", "axis", "target_fusion"], "target_equal"),
        "component_axis": ("BUY_SELL_CASH_PAIRED_CONTRASTS.csv", table, ["year", "axis"], "joint"),
    }
    contrasts, effects = {}, {}
    for layer, (name, expected, groups, reference) in specifications.items():
        frame = read_csv(name)
        check_contrast(frame, expected, groups)
        contrasts[layer] = frame
        effects[layer] = {"reference": reference, "records": summarize(frame, groups)}
    singletons = contrasts["prediction_stream"].loc[contrasts["prediction_stream"].bundle.eq("singleton")]
    effects["prediction_singleton"] = {"reference": "ridge", "records": summarize(singletons, ["year", "axis", "stream"])}
    interactions = read_csv("LAYER_INTERACTIONS.csv")
    require(len(interactions) == len(core) == 21600 and not interactions.duplicated(["year", "axis", "stream", "risk", "optimizer"]).any(), "INCOMPLETE_REGISTERED_INTERACTIONS")
    expected_interaction_keys = set(map(tuple, core[["year", "axis", "stream", "risk", "optimizer"]].to_numpy()))
    require(set(map(tuple, interactions[["year", "axis", "stream", "risk", "optimizer"]].to_numpy())) == expected_interaction_keys, "INTERACTION_KEYS_CHANGED")
    interaction_effects = {}
    for name in ["prediction_x_risk", "prediction_x_optimizer", "risk_x_optimizer", "prediction_x_risk_x_optimizer"]:
        groups = ["year", "axis", "risk", "optimizer"] if name == "risk_x_optimizer" else ["year", "axis", "stream"]
        interaction_effects[name] = summarize(interactions, groups, prefix=name + "__", metric_names=INTERACTION_METRICS)
    fusion_interactions = conditional_fusion_interactions(contrasts["fusion"])
    for name in ["fusion_x_risk", "fusion_x_optimizer", "fusion_x_risk_x_optimizer"]:
        interaction_effects[name] = summarize(fusion_interactions, ["year", "axis", "bundle", "fusion"], prefix=name + "__", metric_names=INTERACTION_METRICS)
    cooperation = read_csv("FUSION_LAYER_INTERACTIONS.csv")
    require(len(cooperation) == len(contrasts["fusion"])+len(contrasts["target_fusion"]), "INCOMPLETE_COOPERATION_INTERACTIONS")
    require(not cooperation.duplicated(["year", "axis", "bundle", "layer", "method", "risk", "optimizer"]).any(), "DUPLICATE_COOPERATION_INTERACTIONS")
    cooperation_key_columns = ["year", "axis", "bundle", "layer", "method", "risk", "optimizer"]
    expected_forecast = contrasts["fusion"].assign(layer="prediction_fusion", method=contrasts["fusion"].fusion)
    expected_target = contrasts["target_fusion"].assign(layer="target_fusion", method=contrasts["target_fusion"].target_fusion)
    expected_cooperation = pd.concat([expected_forecast[cooperation_key_columns], expected_target[cooperation_key_columns]], ignore_index=True)
    require(set(map(tuple, cooperation[cooperation_key_columns].to_numpy())) == set(map(tuple, expected_cooperation.to_numpy())), "COOPERATION_REGISTERED_KEYS_CHANGED")
    forecast_cooperation = cooperation.loc[cooperation.layer.eq("prediction_fusion")]
    compare = fusion_interactions.merge(forecast_cooperation, left_on=["year", "axis", "bundle", "fusion", "risk", "optimizer"],
        right_on=["year", "axis", "bundle", "method", "risk", "optimizer"], validate="one_to_one", suffixes=("", "_main"))
    require(len(compare) == len(fusion_interactions), "COOPERATION_INTERACTION_KEYS_CHANGED")
    for name in ["fusion_x_risk", "fusion_x_optimizer", "fusion_x_risk_x_optimizer"]:
        for metric in INTERACTION_METRICS:
            column = name+"__"+metric
            np.testing.assert_allclose(compare[column], compare[column+"_main"], rtol=1e-10, atol=1e-10, equal_nan=True)
        target_cooperation = cooperation.loc[cooperation.layer.eq("target_fusion")]
        interaction_effects["target_"+name] = summarize(target_cooperation, ["year", "axis", "method"], prefix=name+"__", metric_names=INTERACTION_METRICS)
    configure()
    require(not (OUT / "EFFECTS_SUMMARY.json").exists(), "REFUSE_OVERWRITE_EFFECTS_SUMMARY")
    FIGURES.mkdir(parents=True, exist_ok=True)
    outputs = {}
    scatter_accounts(table, outputs)
    fusion_heatmaps(contrasts["fusion"], outputs)
    risk_optimizer_heatmaps(contrasts["risk"], interactions, outputs)
    for relative, digest in SOURCES.items():
        require(sha(ROOT / relative) == digest, "ANALYSIS_CHANGED_DURING_FIGURES:" + relative)
    summary = {
        "status": "COMPLETE_REGISTERED_DESCRIPTIVE_EFFECTS", "created_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_rows": len(table), "registered_year_strategy_keys": len(keys(table)), "expected_rows": 22176,
        "strategy_count_per_year": 11088, "years": YEARS, "axes": AXES, "source_sha256": SOURCES,
        "producer_sha256": sha(Path(__file__)), "figures": outputs, "figure_count": len(outputs)//2,
        "all_figure_text_bounds_checked": True,
        "global_and_panel_title_spacing_checked": True,
        "heatmap_annotations_within_own_cells_checked": True,
        "fee_annotation_format": "USD, three significant digits; k = 1000 USD; CSV and all underlying statistics unchanged",
        "all_registered_methods_included": True, "training_calls": 0, "new_strategy_calls": 0, "selection_or_tuning_calls": 0,
        "formal_2026_full_pool_status": "BLOCKED_DATA", "year_labels": YEAR_LABELS,
        "sign_tolerance": ZERO_TOLERANCE, "metric_units": {"indicative_return": "fraction", "indicative_max_drawdown": "nonpositive fraction; larger is shallower",
            "mean_gross_exposure": "fraction", "mean_cash": "fraction", "fees": "USD per 1M USD initial account", "half_turnover": "cumulative turnover fraction", "uncertified_days": "days"},
        "interpretation": {"delta": "test method minus its fixed reference at identical registered other components and year/axis; independently advancing actual accounts",
            "return_win_fraction": "positive finite paired return differences, with fixed 1e-12 zero tolerance; descriptive, not significance or a model-selection rule",
            "negative_fraction": "negative finite paired return differences; ties reported separately",
            "aggregation": "median of paired differences, never difference of group medians",
            "interaction": "matched difference-in-differences, aggregated only after individual contrasts; no causal identification claimed",
            "drawdown": "positive delta means a less negative drawdown; inspect exposure and fees jointly",
            "exposure": "actual account mean gross exposure; lower exposure and lower drawdown alone do not demonstrate improved learning",
            "reference_rows": "all reference methods remain included, with their zero paired contrasts",
            "2026": "previously observed Jan-Sep history; qualified-context diagnostic only, not a blind or full-pool test"},
        "coverage_status_counts": coverage.groupby(["year", "status"]).size().reset_index(name="rows").to_dict("records"),
        "paired_effects": effects, "interaction_effects": interaction_effects,
    }
    write_json(OUT / "EFFECTS_SUMMARY.json", summary)
    print(json.dumps({key: summary[key] for key in ["status", "analysis_rows", "figure_count", "all_registered_methods_included", "selection_or_tuning_calls", "formal_2026_full_pool_status"]}))


if __name__ == "__main__":
    main()

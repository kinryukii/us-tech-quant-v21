/* Fixed, dependency-free DOM effects. No data mutation, storage or requests. */
(() => {
  "use strict";
  try {
    const markers = document.querySelectorAll("[data-uq-motion-config]");
    const marker = markers[markers.length - 1];
    if (!marker) return;
    const config = JSON.parse(marker.getAttribute("data-uq-motion-config"));
    if (typeof config.view !== "string" ||
        !(config.decision_date === null || typeof config.decision_date === "string") ||
        typeof config.enabled !== "boolean") return;

    const runtimeKey = Symbol.for("us-tech-quant.motion");
    const state = window[runtimeKey] || (window[runtimeKey] = {
      context: null, enabled: false, active: false, generation: 0, frame: 0,
      animations: new Set(), media: window.matchMedia?.("(prefers-reduced-motion: reduce)"),
      listening: false,
    });
    const root = document.documentElement;
    const stop = () => {
      state.generation += 1;
      if (state.frame) window.cancelAnimationFrame?.(state.frame);
      state.frame = 0;
      for (const animation of state.animations) {
        try { animation.cancel(); } catch (_) { /* Underlying content stays visible. */ }
      }
      state.animations.clear();
    };
    const syncAvailability = () => {
      state.active = state.enabled && state.media?.matches === false;
      root.setAttribute("data-uq-motion", state.active ? "enabled" : "disabled");
      if (!state.active) stop();
    };
    if (!state.listening && state.media?.addEventListener) {
      state.media.addEventListener("change", syncAvailability);
      state.listening = true;
    }

    const previous = state.context;
    const entering = !previous || previous.view !== config.view;
    const changingDate = !!previous && previous.decision_date !== config.decision_date;
    state.context = {view: config.view, decision_date: config.decision_date};
    state.enabled = config.enabled;
    syncAvailability();
    if (!state.active) return;
    // A filter/selection/language rerun must not complete a pending entrance
    // against newly rendered nodes, nor leave detached animated nodes retained.
    if (!entering && !changingDate) {
      stop();
      return;
    }
    stop();
    const generation = state.generation;
    const main = document.querySelector('[data-testid="stMain"]');
    if (!main || !window.requestAnimationFrame) return;

    const visible = (element) => {
      if (!element?.isConnected || !element.getClientRects().length) return false;
      const box = element.getBoundingClientRect();
      return box.bottom > 0 && box.top < window.innerHeight && box.width > 0;
    };
    const find = (selector) => Array.from(main.querySelectorAll(selector)).filter(visible);
    const chartPanels = [
      ".st-key-uq_chart_panel", ".st-key-uq_history_portfolio", ".st-key-uq_history_security",
      ".st-key-uq_performance_path", ".st-key-uq_execution_quality", ".st-key-uq_holding_matrix",
      ".st-key-uq_research_workspace", ".st-key-ml_engine_workspace",
      ".st-key-research_execution_turnover", '[class*="st-key-history_holding_matrix_"]',
    ];
    const uniqueRegions = (selectors) => {
      const targets = Array.from(new Set(selectors.flatMap(find)));
      // One effect per region: a panel and its nested metric/chart must not
      // multiply opacity or move separately. Keep stagger in screen order.
      return targets.filter(element => !targets.some(other =>
        other !== element && other.contains?.(element)
      )).sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
    };
    const play = (element, keyframes, options) => {
      if (typeof element.animate !== "function") return;
      try {
        const animation = element.animate(keyframes, {
          easing: "cubic-bezier(.2,.8,.2,1)", fill: "none", ...options,
        });
        state.animations.add(animation);
        const release = () => state.animations.delete(animation);
        animation.addEventListener?.("finish", release, {once: true});
        animation.addEventListener?.("cancel", release, {once: true});
      } catch (_) { /* No inline opacity/visibility is ever written. */ }
    };
    const enter = () => {
      const selectors = [
        ".uq-page-header", ".uq-metrics", ".uq-snapshot-brief",
        ".uq-system-purpose", ".st-key-uq_decision_focus", ".uq-ml-method-sheet",
        ".uq-table-shell", ".uq-transition-panel",
        ".st-key-uq_inspector", ...chartPanels,
        ".st-key-uq_demo_tour", ".uq-research-evidence", ".uq-research-observation",
        ".uq-history-security-summary", ".uq-date-flow", ".uq-motion-enter",
      ];
      const charts = new Set(chartPanels.flatMap(find));
      uniqueRegions(selectors).forEach((element, index) => {
        // Fade entire chart containers rather than drawing SVG/canvas marks:
        // plotted geometry, hit targets and recorded values stay untouched.
        const chart = charts.has(element);
        play(element, chart ? [{opacity: 0.78}, {opacity: 1}] : [
          {opacity: 0.65, transform: "translateY(12px)"},
          {opacity: 1, transform: "translateY(0)"},
        ], {duration: chart ? 560 : 440, delay: Math.min(index, 5) * 55, fill: "backwards"});
      });
    };
    const emphasizeDate = () => {
      for (const element of find(".uq-date, .uq-snapshot-brief")) {
        play(element, [
          {backgroundColor: "rgba(85,125,64,.17)"},
          {backgroundColor: "rgba(85,125,64,0)"},
        ], {duration: 850});
      }
      for (const element of find(".uq-transition-panel, .uq-change-group")) {
        play(element, [
          {boxShadow: "0 0 0 3px rgba(85,125,64,.16)"},
          {boxShadow: "0 0 0 0 rgba(85,125,64,0)"},
        ], {duration: 700});
      }
      for (const element of uniqueRegions([
        ".uq-table-shell", ...chartPanels, ".uq-date-flow", ".uq-history-security-summary",
        ".uq-research-observation", ".uq-research-evidence",
      ])) {
        play(element, [{opacity: 0.8}, {opacity: 1}], {duration: 260});
      }
    };
    // Wait for the full page's layout without changing scroll or adding a timer.
    state.frame = window.requestAnimationFrame(() => {
      state.frame = window.requestAnimationFrame(() => {
        state.frame = 0;
        if (!state.active || state.generation !== generation) return;
        if (entering) enter();
        else emphasizeDate();
      });
    });
  } catch (_) {
    // A missing node, disabled script or browser API must leave the UI readable.
  }
})();

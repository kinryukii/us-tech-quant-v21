"""Synthetic ML presentation interactions; no model or research-artifact reads."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


def _app():
    import streamlit as st
    from apps.demo_console.components.ml_story import FEATURES, render_feature_atlas, render_learning_story
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.models import DecisionOverview, LearningProfile, ModelVintage, Provenance

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    broken = st.checkbox("Mismatched schema", key="broken")
    failed = st.checkbox("Reader failed", key="failed")
    profile = LearningProfile(
        feature_columns=("foreign_feature",) if broken else tuple(f.name for f in FEATURES),
        parameters=(("max_iter", "123"), ("max_depth", "null")),
        vintages=(ModelVintage(2025, "FINAL", "2024-12-02", "2024-12-31",
                              "2025-01-02", "2025-12-31", 37, 41,
                              "synthetic", "NOT_PERSISTED"),))
    model = DecisionOverview(decision_date="2025-12-03", learning=profile,
                             error="synthetic failure" if failed else None,
                             provenance=Provenance(config_identity="<script>bad</script>"))
    with language_scope(language):
        render_feature_atlas(profile.feature_columns)
        render_learning_story(model, presentation=False)


def _start():
    app = AppTest.from_file(str(Path(__file__)), default_timeout=10).run()
    assert not app.exception
    return app


def _html(app):
    return "\n".join(element.proto.body for element in app.get("html"))


def test_native_feature_selection_survives_language_changes():
    app = _start()
    app.selectbox(key="ml_feature_name").select("ret_120d").run()
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception
        assert app.selectbox(key="ml_feature_name").value == "ret_120d"
        assert "121" in _html(app)
    assert "<script>bad</script>" not in _html(app)
    assert app.code[0].value == "<script>bad</script>"


def test_schema_mismatch_is_visible_and_never_labeled_verified():
    app = _start()
    assert "Matches the recorded feature schema" in _html(app)
    app.checkbox(key="broken").check().run()
    assert not app.exception
    assert "Matches the recorded feature schema" not in _html(app)
    assert len(app.warning) == 1
    assert "not bound" in app.warning[0].value


def test_changing_feature_family_resets_only_the_incompatible_input():
    from apps.demo_console.components.ml_story import FEATURES, GROUPS

    app = _start()
    for group in reversed(GROUPS):
        app.get("button_group")[0].select(group).run()
        assert not app.exception
        available = [feature.name for feature in FEATURES if feature.group == group]
        assert app.selectbox(key="ml_feature_name").value in available
        app.selectbox(key="ml_feature_name").select(available[-1]).run()
        assert not app.exception
        assert app.selectbox(key="ml_feature_name").value == available[-1]
        assert "Definition only" in _html(app)


def test_failed_reader_suppresses_training_records_and_configuration():
    app = _start()
    assert "2024-12-02" in _html(app)
    assert "Maximum boosting iterations" in _html(app)
    app.checkbox(key="failed").check().run()
    assert not app.exception
    assert "2024-12-02" not in _html(app)
    assert "Maximum boosting iterations" not in _html(app)
    assert not app.code
    assert any("metadata is unavailable" in element.value for element in app.caption)


if __name__ == "__main__":
    _app()

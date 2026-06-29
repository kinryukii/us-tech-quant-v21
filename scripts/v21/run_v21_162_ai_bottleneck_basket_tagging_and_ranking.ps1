$ErrorActionPreference = "Stop"

python scripts/v21/v21_162_ai_bottleneck_basket_tagging_and_ranking.py
pytest -q scripts/v21/test_v21_162_ai_bottleneck_basket_tagging_and_ranking.py

$outDir = "outputs/v21/V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING"
Get-Content "$outDir/V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING_report.txt"
Get-Content "$outDir/V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING_summary.json"

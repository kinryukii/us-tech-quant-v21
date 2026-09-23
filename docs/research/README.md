# 研究复用索引

这是既有注册表的派生导航视图，不是新的身份、研究结论或授权依据。旧表字段原样保留；空白表示元数据未登记。
本次读取的 accepted registry head：`65af5778307750e26e3d287ed47d33ad93e7513ba4d2f3d3f6988fc9290756da`。

开始新工作前：先按机制关键词及旧别名 query，并核对未登记的本地源码；再运行既有注册表的 preflight-proposal。
查询覆盖全部注册状态，包括关闭和 tombstone。NOT_FOUND_REQUIRES_REVIEW 不代表允许新建；直接脚本可能未登记，后续研究仍须原有契约。
归档位置只作导航，不改写原冻结引用。状态口径或历史结论不一致会显式提示，不能据此重开研究。
已移除的历史源码仍可通过 [Git 恢复与查重索引](retired_sources.json) 查找；文件退出当前程序不代表其研究结论失效或允许重复开发。

```powershell
python -B scripts/maintenance/research_inventory.py query --repo-root . --text "机制关键词"
python -B scripts/maintenance/research_inventory.py query --repo-root . --alias "旧别名"
python -B -m scripts.maintenance.research_registry preflight-proposal --proposal <proposal.json>
```

| Canonical ID | 当前登记状态 | 旧状态 | 核对 |
| --- | --- | --- | --- |
| [A2_2024_CNMS_SHORT_SALE_PARTICIPATION_INCREMENT](#research-290966c809e67fa8) | CLOSED | — | 无旧状态 |
| [A2_2024_TRANSACTION_COUNT_INCREMENT](#research-64c5c79355c0eda5) | CLOSED | — | 无旧状态 |
| [A2_BIS_POLICY_DIRECTION_BREADTH](#research-726659997032e1c5) | CLOSED | — | 无旧状态 |
| [A2_CFTC_REPORTABLE_PARTICIPATION](#research-2fa0b06b0c93d6c6) | CLOSED | — | 无旧状态 |
| [A2_COST_NAV_REPLAY_ENGINE](#research-0726e9caeea434c4) | ACTIVE | INFRASTRUCTURE_COMPLETE | 需核对 |
| [A2_FISCAL_BILL_MATURITY_INFORMATION](#research-7cc27a58082aecb0) | CLOSED | — | 无旧状态 |
| [A2_FISCAL_GROSS_WITHDRAWAL_ADAPTATION](#research-592d0e3364950290) | CLOSED | — | 无旧状态 |
| [A2_FISCAL_LIQUIDITY_TO_PUBLIC_BILL_ALLOCATION](#research-eaeb2df16cf68587) | CLOSED | — | 无旧状态 |
| [A2_FIXED_BRACKET_OHLC_IDENTIFICATION_20260914](#research-5fda95e30e391a91) | CLOSED | — | 无旧状态 |
| [A2_INTRADAY_CONTINUATION_20260913](#research-1a48874a2f3f91bd) | CLOSED | — | 无旧状态 |
| [A2_INTRADAY_SALIENCE_20260914](#research-04279f01cede0c64) | CLOSED | — | 无旧状态 |
| [A2_PAIRWISE_BREADTH_IDENTIFICATION_20260914](#research-6e8d5dbee43ccd2d) | CLOSED | — | 无旧状态 |
| [A2_SECTOR_NEUTRAL_CONTINUOUS_RANK_RV_V1](#research-b3d4a70c09c177eb) | OPEN | — | 无旧状态 |
| [A2_SESSION_CLOCK_SECOND_MOMENT_20260914](#research-df5b1c72f856db38) | CLOSED | — | 无旧状态 |
| [A2_STATEFUL_REPLACEMENT_MARGIN_R1](#research-94c14796557088b0) | ACTIVE | — | 无旧状态 |
| [A2_SUCCESSOR_CONTROL_S1](#research-10d07e561700d966) | OPEN | FORWARD_ACTIVE_WAIT | 需核对 |
| [A2_SYSTEMATIC_TAIL_DEPENDENCE_20260913](#research-cefa186b6bc44240) | CLOSED | — | 无旧状态 |
| [A2_TEMPORAL_PIT_FEATURE_CONTRACT](#research-01721f5c061f3adc) | ACTIVE | INFRASTRUCTURE_COMPLETE | 需核对 |
| [ACTION_ML_BUY_SELL_SIZING](#research-46ca509d783c9295) | CLOSED | CLOSED_NEGATIVE | 需核对 |
| [ALPHA_MODEL_VARIANT_FORWARD_ARMS](#research-1c2902a081f4d38e) | OPEN | FORWARD_ACTIVE_WAIT | 需核对 |
| [BETA_MATCHED_EXPOSURE_DIAGNOSTICS](#research-af0fef3a83811a0a) | CLOSED | CLOSED_MECHANISM_UNRESOLVED | 需核对 |
| [E5_EXECUTION_HYSTERESIS](#research-26ea85f2273cc088) | OPEN | FORWARD_ACTIVE_WAIT | 需核对 |
| [FIXED_PIT_QQQ_BETA_TARGET_1](#research-e95d6130096d2b50) | OPEN | PARKED_BLOCKED | 需核对 |
| [FULL_POOL_SECTOR_MEMBERSHIP_DECONCENTRATION](#research-6fa10b33697b9805) | CLOSED | CLOSED_NEGATIVE | 需核对 |
| [GENERIC_MARKET_RISK_GROSS_OVERLAYS](#research-303befd82bb122cc) | CLOSED | CLOSED_NEGATIVE | 需核对 |
| [GT40_CANDIDATE_GENERATOR_RECALL](#research-fff6136fb0a553fc) | OPEN | CLOSED_NEGATIVE | 需核对 |
| [INSIDER_H22](#research-8586364a515321b8) | CLOSED | CLOSED_MECHANISM_UNRESOLVED | 需核对 |
| [LOSER_ORTHOGONAL_LOGISTIC_DIAGNOSTIC](#research-916f73c57ea7f53a) | CLOSED | CLOSED_MECHANISM_UNRESOLVED | 需核对 |
| [MINIMUM_JUSTIFIED_SYSTEM_MANIFEST_R1](#research-589da39dc78ebb0c) | ACTIVE | — | 无旧状态 |
| [NG8_TOP60_TO_TOP20_RERANK](#research-707c69b3886ee220) | OPEN | FORWARD_ACTIVE_WAIT | 需核对 |
| [OPEN_ML_FREE_FACTOR_DISCOVERY_LINEAGE](#research-7b6246cf1a1b2a78) | OPEN | — | 无旧状态 |
| [PIT_AS_FILED_SEC_SIC_FF12_FF48_ELIGIBLE_SURFACE](#research-544466dda2df3d24) | ACTIVE | — | 无旧状态 |
| [PORTFOLIO_SYSTEMIC_RISK_OS](#research-03397e73397b3f4f) | CLOSED | CLOSED_NEGATIVE | 需核对 |
| [PORTFOLIO_WEIGHTING_VARIANTS](#research-494506cd8561420c) | CLOSED | CLOSED_NEGATIVE | 需核对 |
| [PRE2026_CAPACITY_E1_DAILY_SURFACE](#research-e6ac2e50eafcfb07) | ACTIVE | — | 无旧状态 |
| [PRE2026_HISTORICAL_SECURITY_IDENTITY_BRIDGE](#research-937c345d02af39ed) | ACTIVE | — | 无旧状态 |
| [PRE2026_SECURITY_FACTOR_RISK_SURFACE](#research-1dfc43ac7521156b) | ACTIVE | — | 无旧状态 |
| [R6_ATTENUATION_POLICY_VARIANTS](#research-36af34fb7d40b769) | CLOSED | CLOSED_NEGATIVE | 需核对 |
| [R6_BAD_ASYMMETRY_SIGNAL](#research-2e491f72c480d2d7) | OPEN | FORWARD_ACTIVE_WAIT | 需核对 |
| [R6_TOP_DECILE_HALF_CASH_POLICY](#research-eada1588528fee88) | OPEN | FORWARD_ACTIVE_WAIT | 需核对 |
| [RAW_A2_BROAD_OOF_PREDICTIONS](#research-27f0517c6221e16d) | ACTIVE | INFRASTRUCTURE_COMPLETE | 需核对 |
| [RAW_A2_HGB_BASELINE](#research-42fe717fbf4a2899) | ACTIVE | INFRASTRUCTURE_COMPLETE | 需核对 |
| [RAW_A2_TOP40_CHECKPOINT](#research-1b52ba954bc9e114) | ACTIVE | INFRASTRUCTURE_COMPLETE | 需核对 |
| [RAW_SCORE_ACTIVE_DEVIATION_ATTENUATION](#research-b9bf51dd8b871740) | OPEN | FORWARD_ACTIVE_WAIT | 需核对 |
| [RX_MARGIN_RANGE_EXHAUSTION_LINEAGE](#research-0fb52d012c8c7e24) | OPEN | — | 无旧状态 |
| [S1_SECTOR_REWEIGHT](#research-111ce587d33cfa92) | OPEN | FORWARD_ACTIVE_WAIT | 需核对 |
| [SECTOR_AWARE_ML_RERANK](#research-770176777bcf0bb6) | OPEN | FROZEN_RESEARCH_CANDIDATE | 需核对 |
| [SECTOR_CASH_AND_GROSS_VARIANTS](#research-f64713885a388f80) | OPEN | FORWARD_ACTIVE_WAIT | 需核对 |
| [SEC_FUNDAMENTAL_CHANGE](#research-00924ca91c2b6e21) | CLOSED | CLOSED_NEGATIVE | 需核对 |
| [SEC_FUNDAMENTAL_CHANGE_R2_WRAPPER](#research-e4b0ae696d350949) | TOMBSTONED | CLOSED_DUPLICATE | 需核对 |
| [SIGNAL_HORIZON_AND_PERSISTENCE](#research-47397aec42248222) | CLOSED | CLOSED_MECHANISM_UNRESOLVED | 需核对 |
| [STOCK_RISK_MODEL_VARIANTS](#research-809f18db3991665e) | CLOSED | CLOSED_NEGATIVE | 需核对 |
| [THIRTEEN_F_CHANGE_STANDALONE](#research-5930d20cd6815a36) | CLOSED | CLOSED_NEGATIVE | 需核对 |
| [THIRTEEN_F_DUAL_SLEEVE](#research-c428334cf9603bd5) | CLOSED | CLOSED_MECHANISM_UNRESOLVED | 需核对 |
| [THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE](#research-d158fc812313a2e4) | OPEN | — | 无旧状态 |
| [TOP20_BOUNDARY_RECOVERY_RERANK](#research-0e874ae3a9171b0d) | TOMBSTONED | CLOSED_DUPLICATE | 需核对 |
| [TOPK_PORTFOLIO_SIZE](#research-c590db10ce57297a) | CLOSED | CLOSED_NEGATIVE | 需核对 |
| [UNIFIED_FORWARD_CONTROL_PLANE](#research-5e41d58291b2f671) | ACTIVE | INFRASTRUCTURE_COMPLETE | 需核对 |
| [WINNER_ORTHOGONAL_LOGISTIC_DIAGNOSTIC](#research-5c47ba6738d417d0) | CLOSED | CLOSED_MECHANISM_UNRESOLVED | 需核对 |
| [WINNER_Q90_NEXTGEN_SIGNAL](#research-d3ff2ecd5496ec10) | OPEN | FORWARD_ACTIVE_WAIT | 需核对 |

点击 ID 跳到对应条目，再展开查看机制、结论、原始引用和别名。

<a id="research-290966c809e67fa8"></a>
<details><summary>A2_2024_CNMS_SHORT_SALE_PARTICIPATION_INCREMENT</summary>

<p><strong>机制 / 假设：</strong>Additional information in reported off-exchange short-sale fraction and its deviation from recent values, conditional on candle state and transaction frequency</p>
<p><strong>登记完成状态：</strong>PARKED</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>UNCOMMITTED_TASK_FILES;strategy_research.py:sha256:e1f7ec7c9d44afe94a07e3b1021e2a6d57c36872e690514323caff4f4895c732;policy_features.py:sha256:38168adafbe2be6bf72c38d93c4cb71f8c0f6b79114122680797ca35e50b0895; C:\Users\Lenovo\Documents\CODING开发\strategy-research-20260914T140537Z\finra_input_contract.json</p>
<p><strong>登记引用：</strong>UNCOMMITTED_TASK_FILES;strategy_research.py:sha256:e1f7ec7c9d44afe94a07e3b1021e2a6d57c36872e690514323caff4f4895c732;policy_features.py:sha256:38168adafbe2be6bf72c38d93c4cb71f8c0f6b79114122680797ca35e50b0895; C:\Users\Lenovo\Documents\CODING开发\strategy-research-20260914T140537Z\finra_input_contract.json</p>
<p><strong>旧别名：</strong>A2_2024_CNMS_SHORT_SALE_PARTICIPATION_INCREMENT</p>
<p><strong>登记别名：</strong>A2_2024_CNMS_SHORT_SALE_PARTICIPATION_INCREMENT</p>
<p><strong>重开条件引用：</strong>receipt://sha256/c1e245f10f012abfb86548fbedcafaee8c54fbbd00e0a92c85a48933f58b8570</p>

</details>

<a id="research-64c5c79355c0eda5"></a>
<details><summary>A2_2024_TRANSACTION_COUNT_INCREMENT</summary>

<p><strong>机制 / 假设：</strong>Aggregate transaction frequency deviation and candle body interaction beyond conditional price information</p>
<p><strong>登记完成状态：</strong>PARKED</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>UNCOMMITTED_TASK_FILES;strategy_research.py:sha256:e1f7ec7c9d44afe94a07e3b1021e2a6d57c36872e690514323caff4f4895c732;policy_features.py:sha256:38168adafbe2be6bf72c38d93c4cb71f8c0f6b79114122680797ca35e50b0895; C:\Users\Lenovo\Documents\CODING开发\strategy-research-20260914T140537Z\input_contract.json</p>
<p><strong>登记引用：</strong>UNCOMMITTED_TASK_FILES;strategy_research.py:sha256:e1f7ec7c9d44afe94a07e3b1021e2a6d57c36872e690514323caff4f4895c732;policy_features.py:sha256:38168adafbe2be6bf72c38d93c4cb71f8c0f6b79114122680797ca35e50b0895; C:\Users\Lenovo\Documents\CODING开发\strategy-research-20260914T140537Z\input_contract.json</p>
<p><strong>旧别名：</strong>A2_2024_TRANSACTION_COUNT_INCREMENT</p>
<p><strong>登记别名：</strong>A2_2024_TRANSACTION_COUNT_INCREMENT</p>
<p><strong>重开条件引用：</strong>receipt://sha256/c983d1ede69f350ee219c1060478a98be6063180c1bf7a126c81a221e69aa0e5</p>

</details>

<a id="research-726659997032e1c5"></a>
<details><summary>A2_BIS_POLICY_DIRECTION_BREADTH</summary>

<p><strong>机制 / 假设：</strong>Commonshorttermpolicyratedirectionandlaterdomesticadjustment</p>
<p><strong>登记完成状态：</strong>PARKED</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>UNKNOWN; C:\Users\Lenovo\Documents\CODING开发\factor-research-20260914T173135Z\input_contract.json</p>
<p><strong>登记引用：</strong>UNKNOWN; C:\Users\Lenovo\Documents\CODING开发\factor-research-20260914T173135Z\input_contract.json</p>
<p><strong>旧别名：</strong>A2_BIS_POLICY_DIRECTION_BREADTH</p>
<p><strong>登记别名：</strong>A2_BIS_POLICY_DIRECTION_BREADTH</p>
<p><strong>重开条件引用：</strong>receipt://sha256/bc6df2bb6aa56627f3ccb92f069ceaeddea89bb9fd3b17a7c595528decc4bf53</p>

</details>

<a id="research-2fa0b06b0c93d6c6"></a>
<details><summary>A2_CFTC_REPORTABLE_PARTICIPATION</summary>

<p><strong>机制 / 假设：</strong>Reported entity participation breadth conditional on open-interest scale</p>
<p><strong>登记完成状态：</strong>PARKED</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>UNKNOWN; C:\Users\Lenovo\Documents\CODING开发\factor-research-20260914T173135Z\cftc_count_input_contract.json</p>
<p><strong>登记引用：</strong>UNKNOWN; C:\Users\Lenovo\Documents\CODING开发\factor-research-20260914T173135Z\cftc_count_input_contract.json</p>
<p><strong>旧别名：</strong>A2_CFTC_REPORTABLE_PARTICIPATION</p>
<p><strong>登记别名：</strong>A2_CFTC_REPORTABLE_PARTICIPATION</p>
<p><strong>重开条件引用：</strong>receipt://sha256/6d47ec15fb8a132e52e133bb68834b5c495f317a81acd7a34a0a935ad3563134</p>

</details>

<a id="research-0726e9caeea434c4"></a>
<details><summary>A2_COST_NAV_REPLAY_ENGINE</summary>

<p><strong>机制 / 假设：</strong>Construct self-financing next-open A2 portfolio economics</p>
<p><strong>旧结论：</strong>Canonical cost and NAV machinery is already shared by later studies</p>
<p><strong>旧状态：</strong>INFRASTRUCTURE_COMPLETE</p>
<p><strong>登记生命周期决策：</strong>KEEP_CORE</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2/portfolio_daily.parquet; D:/us-tech-quant/scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py</p>
<p><strong>旧别名：</strong>R4_PORTFOLIO_TRANSLATION|FAST_A2_R0F1_REPLAY</p>
<p><strong>登记别名：</strong>A2_COST_NAV_REPLAY_ENGINE; FAST_A2_R0F1_REPLAY; R4_PORTFOLIO_TRANSLATION</p>

</details>

<a id="research-7cc27a58082aecb0"></a>
<details><summary>A2_FISCAL_BILL_MATURITY_INFORMATION</summary>

<p><strong>机制 / 假设：</strong>Previously issued Treasury bill allocation schedules as partial advance information about gross administrative outflows</p>
<p><strong>登记完成状态：</strong>COMPLETED</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>UNKNOWN; C:/Users/Lenovo/Documents/CODING开发/factor-research-20260914T173135Z/auction_input_contract.json</p>
<p><strong>登记引用：</strong>UNKNOWN; C:/Users/Lenovo/Documents/CODING开发/factor-research-20260914T173135Z/auction_input_contract.json</p>
<p><strong>旧别名：</strong>A2_FISCAL_BILL_MATURITY_INFORMATION</p>
<p><strong>登记别名：</strong>A2_FISCAL_BILL_MATURITY_INFORMATION</p>
<p><strong>重开条件引用：</strong>receipt://sha256/cc4399c08a2fb8bad8f486792b8c4b600f3a45586e283f7335bac59dd2957a3b</p>

</details>

<a id="research-592d0e3364950290"></a>
<details><summary>A2_FISCAL_GROSS_WITHDRAWAL_ADAPTATION</summary>

<p><strong>机制 / 假设：</strong>Recent gross administrative withdrawal level adaptation</p>
<p><strong>登记完成状态：</strong>PARKED</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>UNKNOWN; C:\Users\Lenovo\Documents\CODING开发\factor-research-20260914T173135Z\fiscal_mechanism_v2_input_refs.json</p>
<p><strong>登记引用：</strong>UNKNOWN; C:\Users\Lenovo\Documents\CODING开发\factor-research-20260914T173135Z\fiscal_mechanism_v2_input_refs.json</p>
<p><strong>旧别名：</strong>A2_FISCAL_GROSS_WITHDRAWAL_ADAPTATION</p>
<p><strong>登记别名：</strong>A2_FISCAL_GROSS_WITHDRAWAL_ADAPTATION</p>
<p><strong>重开条件引用：</strong>receipt://sha256/ceb89c1a70cb3f8acd3977b5f3d80a06d4b555ec6e3cdc41279fe1da86c83783</p>

</details>

<a id="research-eaeb2df16cf68587"></a>
<details><summary>A2_FISCAL_LIQUIDITY_TO_PUBLIC_BILL_ALLOCATION</summary>

<p><strong>机制 / 假设：</strong>Treasury published liquidity coverage and subsequent primary Bill financing after known maturity commitments and recent issued allocations</p>
<p><strong>登记完成状态：</strong>PARKED</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>UNKNOWN; C:\Users\Lenovo\Documents\CODING开发\factor-research-20260914T173135Z\auction_input_contract.json;C:\Users\Lenovo\Documents\CODING开发\factor-research-20260914T173135Z\input_contract.json</p>
<p><strong>登记引用：</strong>UNKNOWN; C:\Users\Lenovo\Documents\CODING开发\factor-research-20260914T173135Z\auction_input_contract.json;C:\Users\Lenovo\Documents\CODING开发\factor-research-20260914T173135Z\input_contract.json</p>
<p><strong>旧别名：</strong>A2_FISCAL_LIQUIDITY_TO_PUBLIC_BILL_ALLOCATION</p>
<p><strong>登记别名：</strong>A2_FISCAL_LIQUIDITY_TO_PUBLIC_BILL_ALLOCATION</p>
<p><strong>重开条件引用：</strong>receipt://sha256/646401a0e77d2de896d57bf30beaee097acbe1ab90e1df51d830c19c026e11ee</p>

</details>

<a id="research-5fda95e30e391a91"></a>
<details><summary>A2_FIXED_BRACKET_OHLC_IDENTIFICATION_20260914</summary>

<p><strong>机制 / 假设：</strong>PRECOMMITTED_DOWNSIDE_UPSIDE_EXIT_FIRST_PASSAGE_WITH_UNOBSERVED_ORDER</p>
<p><strong>登记完成状态：</strong>PARKED</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>source-sha256:88a0d26bac996638d9bd645962d82386c83bbab3e9a45c783a9d0fd4ffe933e7; C:\Users\Lenovo\Documents\CODING开发\rolling-research-20260914T072731Z\barrier_policy_data_contract.json</p>
<p><strong>登记引用：</strong>source-sha256:88a0d26bac996638d9bd645962d82386c83bbab3e9a45c783a9d0fd4ffe933e7; C:\Users\Lenovo\Documents\CODING开发\rolling-research-20260914T072731Z\barrier_policy_data_contract.json</p>
<p><strong>旧别名：</strong>A2_FIXED_BRACKET_OHLC_IDENTIFICATION_20260914</p>
<p><strong>登记别名：</strong>A2_FIXED_BRACKET_OHLC_IDENTIFICATION_20260914</p>
<p><strong>重开条件引用：</strong>receipt://sha256/280590542db450c2d42ad3b72372dd95902d0994e00065d4c4c792fd01aa3261</p>

</details>

<a id="research-1a48874a2f3f91bd"></a>
<details><summary>A2_INTRADAY_CONTINUATION_20260913</summary>

<p><strong>机制 / 假设：</strong>PERSISTENT_SAME_SESSION_INVESTOR_PARTICIPATION_PRIOR_COMPLETED_MONTH_INTRADAY_CONTINUATION</p>
<p><strong>登记完成状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>sha256:cebd00cad05e32c3fed9afb583ee223c2441bdb95b7fd4fda871029862c7124d; C:\Users\Lenovo\Documents\CODING开发\strategy-lab-20260913\audits\intraday_data_execution_evidence.md</p>
<p><strong>登记引用：</strong>sha256:cebd00cad05e32c3fed9afb583ee223c2441bdb95b7fd4fda871029862c7124d; C:\Users\Lenovo\Documents\CODING开发\strategy-lab-20260913\audits\intraday_data_execution_evidence.md</p>
<p><strong>旧别名：</strong>A2_INTRADAY_CONTINUATION_20260913</p>
<p><strong>登记别名：</strong>A2_INTRADAY_CONTINUATION_20260913</p>
<p><strong>重开条件引用：</strong>receipt://sha256/47a98dfcda566b14ea8da647cecfd5838aa8dc57d3823fc4c3fe921633e50ba0</p>

</details>

<a id="research-04279f01cede0c64"></a>
<details><summary>A2_INTRADAY_SALIENCE_20260914</summary>

<p><strong>机制 / 假设：</strong>MONTHLY_INTRADAY_STATE_PROMINENCE_RELATIVE_TO_MARKET_CONTEXT</p>
<p><strong>登记完成状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>source-sha256:14061a561b1d90c7ef36321d60b2bce77e6038259e4234b87f0391bdb3e9eb99; D:\us-tech-quant-results\A2_INTRADAY_CONTINUATION_20260913\data_contract.json</p>
<p><strong>登记引用：</strong>source-sha256:14061a561b1d90c7ef36321d60b2bce77e6038259e4234b87f0391bdb3e9eb99; D:\us-tech-quant-results\A2_INTRADAY_CONTINUATION_20260913\data_contract.json</p>
<p><strong>旧别名：</strong>A2_INTRADAY_SALIENCE_20260914</p>
<p><strong>登记别名：</strong>A2_INTRADAY_SALIENCE_20260914</p>
<p><strong>重开条件引用：</strong>receipt://sha256/b34dae5f6601a87fb59dd8bc1237dfbb2abdbd07125cd4151fe2763ed5dc1aae</p>

</details>

<a id="research-6e8d5dbee43ccd2d"></a>
<details><summary>A2_PAIRWISE_BREADTH_IDENTIFICATION_20260914</summary>

<p><strong>机制 / 假设：</strong>HIGHER_ORDER_JOINT_BREADTH_MASS_UNDETERMINED_BY_FIXED_PAIRWISE_LAWS</p>
<p><strong>登记完成状态：</strong>PARKED</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>source-sha256:c5e9acbb1ddf634593f12921096a4d1a2a5e1c156f63cf07522b4e788a8a1b6c; C:\Users\Lenovo\Documents\CODING开发\rolling-research-20260914T072731Z\pairwise_breadth_data_contract.json</p>
<p><strong>登记引用：</strong>source-sha256:c5e9acbb1ddf634593f12921096a4d1a2a5e1c156f63cf07522b4e788a8a1b6c; C:\Users\Lenovo\Documents\CODING开发\rolling-research-20260914T072731Z\pairwise_breadth_data_contract.json</p>
<p><strong>旧别名：</strong>A2_PAIRWISE_BREADTH_IDENTIFICATION_20260914</p>
<p><strong>登记别名：</strong>A2_PAIRWISE_BREADTH_IDENTIFICATION_20260914</p>
<p><strong>重开条件引用：</strong>receipt://sha256/9e0972830c6787a25127af5dc97abc6643ae7de5e9b94ff05ac3f8ce4aae2690</p>

</details>

<a id="research-b3d4a70c09c177eb"></a>
<details><summary>A2_SECTOR_NEUTRAL_CONTINUOUS_RANK_RV_V1</summary>

<p><strong>机制 / 假设：</strong>A_RAW_A2_DISTINCT_PORTFOLIO_GEOMETRY</p>
<p><strong>旧结论：</strong>The only certified PIT taxonomy physical keyset is Raw A2 Top20 and every valid mapped row is a Top20 subset; the no-cutoff eligible-universe sleeve cannot be constructed without changing the frozen contract.</p>
<p><strong>登记生命周期决策：</strong>UNTESTABLE_AUTHORITATIVE_DATA_GAP</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/rv_contract.json; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/postfreeze_source_resolution_addendum.json; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/authority_reconciliation.json; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/coverage_report.csv; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/final_research_report.md; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/final_validation.json; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/final_independent_review.md</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/rv_contract.json; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/postfreeze_source_resolution_addendum.json; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/authority_reconciliation.json; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/coverage_report.csv; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/final_research_report.md; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/final_validation.json; D:/us-tech-quant-results/A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1/final_independent_review.md</p>
<p><strong>旧别名：</strong>A2_SECTOR_NEUTRAL_CONTINUOUS_RANK_RV_V1; A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1</p>
<p><strong>登记别名：</strong>A2_SECTOR_NEUTRAL_CONTINUOUS_RANK_RV_V1; A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1</p>

</details>

<a id="research-df5b1c72f856db38"></a>
<details><summary>A2_SESSION_CLOCK_SECOND_MOMENT_20260914</summary>

<p><strong>机制 / 假设：</strong>PREANNOUNCED_TRADING_DURATION_AND_INTRADAY_INNOVATION_ACCUMULATION</p>
<p><strong>登记完成状态：</strong>PARKED</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>source-sha256:52be821fff89f4270a6a4547d9f9968c608ab99ded6e684d406a7e842f90abec; C:\Users\Lenovo\Documents\CODING开发\rolling-research-20260914T072731Z\session_clock_data_contract.json</p>
<p><strong>登记引用：</strong>source-sha256:52be821fff89f4270a6a4547d9f9968c608ab99ded6e684d406a7e842f90abec; C:\Users\Lenovo\Documents\CODING开发\rolling-research-20260914T072731Z\session_clock_data_contract.json</p>
<p><strong>旧别名：</strong>A2_SESSION_CLOCK_SECOND_MOMENT_20260914</p>
<p><strong>登记别名：</strong>A2_SESSION_CLOCK_SECOND_MOMENT_20260914</p>
<p><strong>重开条件引用：</strong>receipt://sha256/8dfc67577d5ce7a26d4dcf4056964e9aed8fe039ee78a8cb47027e8630db4a76</p>

</details>

<a id="research-94c14796557088b0"></a>
<details><summary>A2_STATEFUL_REPLACEMENT_MARGIN_R1</summary>

<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>authority://git/a62d69e3e01ccc11de976b5295404ae3d18cc1b0/a2-stateful-replacement-margin-r1-inputs</p>
<p><strong>登记引用：</strong>authority://git/a62d69e3e01ccc11de976b5295404ae3d18cc1b0/a2-stateful-replacement-margin-r1-inputs</p>
<p><strong>旧别名：</strong>A2_STATEFUL_REPLACEMENT_MARGIN_R1</p>
<p><strong>登记别名：</strong>A2_STATEFUL_REPLACEMENT_MARGIN_R1</p>

</details>

<a id="research-10d07e561700d966"></a>
<details><summary>A2_SUCCESSOR_CONTROL_S1</summary>

<p><strong>机制 / 假设：</strong>Repackage the same frozen A2 fit for a complete 613-name successor universe</p>
<p><strong>旧结论：</strong>Same fitted artifact but materially different frozen universe and deployment lineage; not a new alpha mechanism</p>
<p><strong>旧状态：</strong>FORWARD_ACTIVE_WAIT</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/a2_successor_s1/successor_control.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_SUCCESSOR_FORWARD_SHADOW_S1/registry/control_identity.json; D:/us-tech-quant/config/a2_successor_s1/control_contract.json; D:/us-tech-quant/scripts/a2_successor_s1/successor_control.py</p>
<p><strong>旧别名：</strong>A2_SUCCESSOR_FORWARD_SHADOW_S1|A2_SUCCESSOR_FIXED_SPEC_S1</p>
<p><strong>登记别名：</strong>A2_SUCCESSOR_CONTROL_S1; A2_SUCCESSOR_FIXED_SPEC_S1; A2_SUCCESSOR_FORWARD_SHADOW_S1</p>

</details>

<a id="research-cefa186b6bc44240"></a>
<details><summary>A2_SYSTEMATIC_TAIL_DEPENDENCE_20260913</summary>

<p><strong>机制 / 假设：</strong>JOINT_STOCK_MARKET_SIGN_AND_THIRD_MOMENT_EXPOSURES_INCREMENTAL_TO_OWN_VOLATILITY_AND_LINEAR_MARKET_EXPOSURE</p>
<p><strong>登记完成状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>sha256:a9a0171f2f5c7b2c2714b12b20600afce683a4cd360adcdaff2041d064bfcd80; D:/us-tech-quant-results/A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2/surface_manifest.json</p>
<p><strong>登记引用：</strong>sha256:a9a0171f2f5c7b2c2714b12b20600afce683a4cd360adcdaff2041d064bfcd80; D:/us-tech-quant-results/A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2/surface_manifest.json</p>
<p><strong>旧别名：</strong>A2_SYSTEMATIC_TAIL_DEPENDENCE_20260913</p>
<p><strong>登记别名：</strong>A2_SYSTEMATIC_TAIL_DEPENDENCE_20260913</p>
<p><strong>重开条件引用：</strong>receipt://sha256/73444e9efb43a515303cd072b68a0c74063ced8da5bc51858adf44331ca66429</p>

</details>

<a id="research-01721f5c061f3adc"></a>
<details><summary>A2_TEMPORAL_PIT_FEATURE_CONTRACT</summary>

<p><strong>机制 / 假设：</strong>Freeze feature availability and temporal OOS folds</p>
<p><strong>旧结论：</strong>Authoritative folds and PIT features already exist; competing frameworks are duplicate infrastructure</p>
<p><strong>旧状态：</strong>INFRASTRUCTURE_COMPLETE</p>
<p><strong>登记生命周期决策：</strong>KEEP_CORE</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_MODEL_FAMILY_R1A_DATA_COMPLETE/incumbent_model_contract.json</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_MODEL_FAMILY_R1A_DATA_COMPLETE/fold_manifest.csv; D:/us-tech-quant-results/A2_MODEL_FAMILY_R1A_DATA_COMPLETE/incumbent_model_contract.json; D:/us-tech-quant-results/A2_PIT_DATA_COVERAGE_R1/pit_feature_rows.parquet</p>
<p><strong>旧别名：</strong>MODEL_FAMILY_R1A_FOLDS|PIT_DATA_COVERAGE_R1</p>
<p><strong>登记别名：</strong>A2_TEMPORAL_PIT_FEATURE_CONTRACT; MODEL_FAMILY_R1A_FOLDS; PIT_DATA_COVERAGE_R1</p>

</details>

<a id="research-46ca509d783c9295"></a>
<details><summary>ACTION_ML_BUY_SELL_SIZING</summary>

<p><strong>机制 / 假设：</strong>Learn BUY ADD HOLD REDUCE EXIT and replacement or sizing actions</p>
<p><strong>旧结论：</strong>Security-level Action ML and sizing were already tested with corrected labels and no robust edge</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>CLOSED_PRIOR_UNCHANGED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_global_ff12_hold_replace_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_CLEAN_LABEL_LINEAGE_AND_AUTONOMOUS_POLICY_R2/final_report.md; D:/us-tech-quant/scripts/v22/a2_global_ff12_hold_replace_r1.py</p>
<p><strong>旧别名：</strong>ACTION_ML|BUY_SELL_SIZING|GLOBAL_FF12_HOLD_REPLACE|CLEAN_LABEL_AUTONOMOUS_POLICY_R2</p>
<p><strong>登记别名：</strong>ACTION_ML; ACTION_ML_BUY_SELL_SIZING; BUY_SELL_SIZING; CLEAN_LABEL_AUTONOMOUS_POLICY_R2; GLOBAL_FF12_HOLD_REPLACE</p>

</details>

<a id="research-1c2902a081f4d38e"></a>
<details><summary>ALPHA_MODEL_VARIANT_FORWARD_ARMS</summary>

<p><strong>机制 / 假设：</strong>Observe previously tested alpha-model variants without retuning</p>
<p><strong>旧结论：</strong>Model-family challenger work is complete and represented only as frozen forward comparison</p>
<p><strong>旧状态：</strong>FORWARD_ACTIVE_WAIT</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_ALGORITHM_R2A_2026_RETROSPECTIVE_AND_FORWARD_SHADOW_ANCHOR/forward_shadow_contract.json</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_ALGORITHM_R2A_2026_RETROSPECTIVE_AND_FORWARD_SHADOW_ANCHOR/forward_shadow_contract.json; D:/us-tech-quant-results/A2_MODEL_FAMILY_R1A_DATA_COMPLETE/freeze_manifest.json</p>
<p><strong>旧别名：</strong>M1_XGB_REG|M2_W50|ALGORITHM_R2A_FORWARD_SHADOW</p>
<p><strong>登记别名：</strong>ALGORITHM_R2A_FORWARD_SHADOW; ALPHA_MODEL_VARIANT_FORWARD_ARMS; M1_XGB_REG; M2_W50</p>

</details>

<a id="research-af0fef3a83811a0a"></a>
<details><summary>BETA_MATCHED_EXPOSURE_DIAGNOSTICS</summary>

<p><strong>机制 / 假设：</strong>Measure whether A2 economics are explained by market and technology exposure</p>
<p><strong>旧结论：</strong>Ex-post exposure evidence is authoritative as a diagnostic but cannot define an ex-ante beta policy</p>
<p><strong>旧状态：</strong>CLOSED_MECHANISM_UNRESOLVED</p>
<p><strong>登记生命周期决策：</strong>PARK_MECHANISM_UNRESOLVED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_beta_matched_benchmark_and_residual_value_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_BETA_MATCHED_BENCHMARK_AND_RESIDUAL_VALUE_R1/final_report.md; D:/us-tech-quant/scripts/v22/a2_beta_matched_benchmark_and_residual_value_r1.py</p>
<p><strong>旧别名：</strong>QQQ_BETA|SOXX_BETA|BETA_MATCHED|VOL_MATCHED|RESIDUAL_SHARPE</p>
<p><strong>登记别名：</strong>BETA_MATCHED; BETA_MATCHED_EXPOSURE_DIAGNOSTICS; QQQ_BETA; RESIDUAL_SHARPE; SOXX_BETA; VOL_MATCHED</p>

</details>

<a id="research-26ea85f2273cc088"></a>
<details><summary>E5_EXECUTION_HYSTERESIS</summary>

<p><strong>机制 / 假设：</strong>Reduce boundary churn without changing intended Raw A2 Top20</p>
<p><strong>旧结论：</strong>Turnover and one-session persistence are already represented by a frozen execution overlay</p>
<p><strong>旧状态：</strong>FORWARD_ACTIVE_WAIT</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS/execution_r2_preregistered_contract.json</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS/execution_r2_preregistered_contract.json; D:/us-tech-quant-results/A2_EXECUTION_R3_FORWARD_SHADOW/execution_forward_shadow_contract.json</p>
<p><strong>旧别名：</strong>EXECUTION_EFFICIENCY_R2|E5_COMBINED_CONSERVATIVE|EXECUTION_R3_FORWARD</p>
<p><strong>登记别名：</strong>E5_COMBINED_CONSERVATIVE; E5_EXECUTION_HYSTERESIS; EXECUTION_EFFICIENCY_R2; EXECUTION_R3_FORWARD</p>

</details>

<a id="research-e95d6130096d2b50"></a>
<details><summary>FIXED_PIT_QQQ_BETA_TARGET_1</summary>

<p><strong>机制 / 假设：</strong>Normalize unchanged Raw A2 to ex-ante QQQ beta 1.00</p>
<p><strong>旧结论：</strong>No economic test occurred; Risk OS SPY beta 1.50 is materially different</p>
<p><strong>旧状态：</strong>PARKED_BLOCKED</p>
<p><strong>登记生命周期决策：</strong>UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_FIXED_EXANTE_QQQ_BETA_NORMALIZATION_R1/final_report.md</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_FIXED_EXANTE_QQQ_BETA_NORMALIZATION_R1/final_report.md; D:/us-tech-quant-results/A2_FIXED_EXANTE_QQQ_BETA_NORMALIZATION_R1/hash_manifest.json</p>
<p><strong>旧别名：</strong>A2_FIXED_EXANTE_QQQ_BETA_NORMALIZATION_R1</p>
<p><strong>登记别名：</strong>A2_FIXED_EXANTE_QQQ_BETA_NORMALIZATION_R1; FIXED_PIT_QQQ_BETA_TARGET_1</p>

</details>

<a id="research-6fa10b33697b9805"></a>
<details><summary>FULL_POOL_SECTOR_MEMBERSHIP_DECONCENTRATION</summary>

<p><strong>机制 / 假设：</strong>Select less-crowded names from the existing broad Raw A2 pool</p>
<p><strong>旧结论：</strong>Candidate-level sector deconcentration was tested and incurred excessive alpha loss</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>CLOSED_PRIOR_UNCHANGED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_PRETOP20_CANDIDATE_RECOVERY_AND_MEMBERSHIP_DECONCENTRATION_R1/final_report.md; D:/us-tech-quant/scripts/v22/a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py</p>
<p><strong>旧别名：</strong>PRETOP20_M1_FIXED_DUAL_MARGINAL_MEMBERSHIP</p>
<p><strong>登记别名：</strong>FULL_POOL_SECTOR_MEMBERSHIP_DECONCENTRATION; PRETOP20_M1_FIXED_DUAL_MARGINAL_MEMBERSHIP</p>

</details>

<a id="research-303befd82bb122cc"></a>
<details><summary>GENERIC_MARKET_RISK_GROSS_OVERLAYS</summary>

<p><strong>机制 / 假设：</strong>Reduce gross based on observed or predicted risk state</p>
<p><strong>旧结论：</strong>VIX trend volatility and gross-scaling variants are saturated; new thresholds are parameter search</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>CLOSED_PRIOR_UNCHANGED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_trend_regime_overlay_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_TREND_REGIME_OVERLAY_R1/final_report.md; D:/us-tech-quant/scripts/v22/a2_trend_regime_overlay_r1.py</p>
<p><strong>旧别名：</strong>VIX_GATE|TREND_REGIME|VOLATILITY_TARGET|RISK_ML_R1B|DYNAMIC_GROSS</p>
<p><strong>登记别名：</strong>DYNAMIC_GROSS; GENERIC_MARKET_RISK_GROSS_OVERLAYS; RISK_ML_R1B; TREND_REGIME; VIX_GATE; VOLATILITY_TARGET</p>

</details>

<a id="research-fff6136fb0a553fc"></a>
<details><summary>GT40_CANDIDATE_GENERATOR_RECALL</summary>

<p><strong>机制 / 假设：</strong>Determine fixed winner-label recall by existing Raw A2 ranks beyond 40</p>
<p><strong>旧结论：</strong>GT40 winner mass and existing Q90 lift were materially present beyond Top40, but the signal was strongly confounded by existing PIT volatility and candidate augmentation was not justified.</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE</p>
<p><strong>状态核对：</strong>CONFLICT_LEGACY_CLOSED_CURRENT_NONTERMINAL_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2/oof_predictions.parquet; D:/us-tech-quant/scripts/v22/a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py</p>
<p><strong>旧别名：</strong>CANDIDATE_GENERATOR_GAP|RANK_GT40_WINNER_RECALL</p>
<p><strong>登记别名：</strong>CANDIDATE_GENERATOR_GAP; GT40_CANDIDATE_GENERATOR_RECALL; RANK_GT40_WINNER_RECALL</p>

</details>

<a id="research-8586364a515321b8"></a>
<details><summary>INSIDER_H22</summary>

<p><strong>机制 / 假设：</strong>Use clustered insider purchases as a distinct filing alpha</p>
<p><strong>旧结论：</strong>Binary term drove replacements but did not coherently explain the observed effect; another insider model would be a model variant</p>
<p><strong>旧状态：</strong>CLOSED_MECHANISM_UNRESOLVED</p>
<p><strong>登记生命周期决策：</strong>PARK_MECHANISM_UNRESOLVED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/H22_CLUSTERED_INSIDER_ACTIVITY/final_report.md</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/H22_CLUSTERED_INSIDER_ACTIVITY/final_report.md; D:/us-tech-quant-results/H22_CLUSTERED_INSIDER_ACTIVITY/trial_ledger.json</p>
<p><strong>旧别名：</strong>H22_CLUSTERED_INSIDER_ACTIVITY|FORM4_R1</p>
<p><strong>登记别名：</strong>FORM4_R1; H22_CLUSTERED_INSIDER_ACTIVITY; INSIDER_H22</p>

</details>

<a id="research-916f73c57ea7f53a"></a>
<details><summary>LOSER_ORTHOGONAL_LOGISTIC_DIAGNOSTIC</summary>

<p><strong>机制 / 假设：</strong>Test learnability of the R6 label without reconstructing Raw A2</p>
<p><strong>旧结论：</strong>Label and folds reuse R6 but prediction values cannot be certified identical and the model intentionally differs</p>
<p><strong>旧状态：</strong>CLOSED_MECHANISM_UNRESOLVED</p>
<p><strong>登记生命周期决策：</strong>PARK_MECHANISM_UNRESOLVED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1/final_report.md</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1/final_report.md; D:/us-tech-quant-results/A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1/winner_loser_learnability_recall.csv</p>
<p><strong>旧别名：</strong>CANONICAL_ATTRIBUTION_LOSER_MODEL</p>
<p><strong>登记别名：</strong>CANONICAL_ATTRIBUTION_LOSER_MODEL; LOSER_ORTHOGONAL_LOGISTIC_DIAGNOSTIC</p>

</details>

<a id="research-589da39dc78ebb0c"></a>
<details><summary>MINIMUM_JUSTIFIED_SYSTEM_MANIFEST_R1</summary>

<p><strong>旧结论：</strong>Query anchor for the validated minimum-system manifest; not a tradable component.</p>
<p><strong>登记生命周期决策：</strong>KEEP_CORE</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>D:\us-tech-quant-results\A2_MINIMUM_JUSTIFIED_SYSTEM_AND_COMPONENT_INCREMENTALITY_AUDIT_R1\minimum_justified_system.json; D:\us-tech-quant-results\A2_MINIMUM_JUSTIFIED_SYSTEM_AND_COMPONENT_INCREMENTALITY_AUDIT_R1\component_decisions.json; D:/us-tech-quant-results/etc2/EFFECTIVE_RESEARCH_TRIAL_LEDGER_CLOSURE_R3/effective_trial_ledger.json</p>
<p><strong>登记引用：</strong>D:\us-tech-quant-results\A2_MINIMUM_JUSTIFIED_SYSTEM_AND_COMPONENT_INCREMENTALITY_AUDIT_R1\minimum_justified_system.json; D:\us-tech-quant-results\A2_MINIMUM_JUSTIFIED_SYSTEM_AND_COMPONENT_INCREMENTALITY_AUDIT_R1\component_decisions.json; D:/us-tech-quant-results/etc2/EFFECTIVE_RESEARCH_TRIAL_LEDGER_CLOSURE_R3/effective_trial_ledger.json</p>
<p><strong>旧别名：</strong>A2_MINIMUM_SYSTEM_R1; MINIMUM_JUSTIFIED_SYSTEM; MINIMUM_JUSTIFIED_SYSTEM_MANIFEST_R1</p>
<p><strong>登记别名：</strong>A2_MINIMUM_SYSTEM_R1; MINIMUM_JUSTIFIED_SYSTEM; MINIMUM_JUSTIFIED_SYSTEM_MANIFEST_R1</p>

</details>

<a id="research-707c69b3886ee220"></a>
<details><summary>NG8_TOP60_TO_TOP20_RERANK</summary>

<p><strong>机制 / 假设：</strong>Recover winners by reranking Raw A2 Top60 into Top20</p>
<p><strong>旧结论：</strong>Top60-to-Top20 reranking has already been historically tested and frozen for forward observation</p>
<p><strong>旧状态：</strong>FORWARD_ACTIVE_WAIT</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_nextgen_topk_ensemble_rerank_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_NG8_RISK_R2_TRUE_PROSPECTIVE_FORWARD_CHAIN_R1/forward_contract.json; D:/us-tech-quant/scripts/v22/a2_nextgen_topk_ensemble_rerank_r1.py</p>
<p><strong>旧别名：</strong>NEXTGEN_TOPK_ENSEMBLE_RERANK_R1|NG8_FIXED_QUANTILE__FIXED_CONFIDENCE_REPLACEMENT</p>
<p><strong>登记别名：</strong>NEXTGEN_TOPK_ENSEMBLE_RERANK_R1; NG8_FIXED_QUANTILE__FIXED_CONFIDENCE_REPLACEMENT; NG8_TOP60_TO_TOP20_RERANK</p>

</details>

<a id="research-7b6246cf1a1b2a78"></a>
<details><summary>OPEN_ML_FREE_FACTOR_DISCOVERY_LINEAGE</summary>

<p><strong>机制 / 假设：</strong>Open ML and free-factor discovery lineage named by the human audit contract</p>
<p><strong>旧结论：</strong>Safe authoritative evidence is insufficient; the component remains unresolved without a negative inference.</p>
<p><strong>登记生命周期决策：</strong>UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>旧别名：</strong>FREE_FACTOR_DISCOVERY; OPEN_ML_DISCOVERY; OPEN_ML_FREE_FACTOR_DISCOVERY_LINEAGE</p>
<p><strong>登记别名：</strong>FREE_FACTOR_DISCOVERY; OPEN_ML_DISCOVERY; OPEN_ML_FREE_FACTOR_DISCOVERY_LINEAGE</p>

</details>

<a id="research-544466dda2df3d24"></a>
<details><summary>PIT_AS_FILED_SEC_SIC_FF12_FF48_ELIGIBLE_SURFACE</summary>

<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>D:\us-tech-quant-results\A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1\pit_sec_sic_ff12_ff48_eligible_surface.parquet; D:\us-tech-quant-results\A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1\updated_pit_sec_sic_ff12_ff48_surface.parquet; D:\us-tech-quant-results\A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1\taxonomy_surface_manifest.json; D:\us-tech-quant-results\A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1\counterfactual_readiness.json; D:\us-tech-quant-results\A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1\final_validation.json; D:\us-tech-quant-results\A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1\final_independent_review.md</p>
<p><strong>登记引用：</strong>D:\us-tech-quant-results\A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1\pit_sec_sic_ff12_ff48_eligible_surface.parquet; D:\us-tech-quant-results\A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1\updated_pit_sec_sic_ff12_ff48_surface.parquet; D:\us-tech-quant-results\A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1\taxonomy_surface_manifest.json; D:\us-tech-quant-results\A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1\counterfactual_readiness.json; D:\us-tech-quant-results\A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1\final_validation.json; D:\us-tech-quant-results\A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1\final_independent_review.md</p>
<p><strong>旧别名：</strong>PIT AS FILED SEC SIC FF12 FF48 ELIGIBLE SURFACE</p>
<p><strong>登记别名：</strong>PIT AS FILED SEC SIC FF12 FF48 ELIGIBLE SURFACE</p>

</details>

<a id="research-03397e73397b3f4f"></a>
<details><summary>PORTFOLIO_SYSTEMIC_RISK_OS</summary>

<p><strong>机制 / 假设：</strong>Time portfolio-wide systemic de-risking</p>
<p><strong>旧结论：</strong>Portfolio timing branch failed its pre-2026 predictive and economic gate</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>CLOSED_PRIOR_UNCHANGED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_risk_os_r2.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_RISK_OS_R2/risk_os_r2_final_summary.json; D:/us-tech-quant/scripts/v22/a2_risk_os_r2.py</p>
<p><strong>旧别名：</strong>RISK_OS_R1|RISK_OS_R2</p>
<p><strong>登记别名：</strong>PORTFOLIO_SYSTEMIC_RISK_OS; RISK_OS_R1; RISK_OS_R2</p>

</details>

<a id="research-494506cd8561420c"></a>
<details><summary>PORTFOLIO_WEIGHTING_VARIANTS</summary>

<p><strong>机制 / 假设：</strong>Alter weights without new independent information</p>
<p><strong>旧结论：</strong>Weighting and sizing actions were tested; coefficients or bounds are parameter variants</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>CLOSED_PRIOR_UNCHANGED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_autonomous_buy_sell_and_sizing_policy_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_CLEAN_LABEL_LINEAGE_AND_AUTONOMOUS_POLICY_R2/final_report.md; D:/us-tech-quant/scripts/v22/a2_autonomous_buy_sell_and_sizing_policy_r1.py</p>
<p><strong>旧别名：</strong>SCORE_WEIGHTING|EQUAL_WEIGHTING|VOLATILITY_WEIGHTING|INDUSTRY_WEIGHTING|FIXED_ATTENUATION</p>
<p><strong>登记别名：</strong>EQUAL_WEIGHTING; FIXED_ATTENUATION; INDUSTRY_WEIGHTING; PORTFOLIO_WEIGHTING_VARIANTS; SCORE_WEIGHTING; VOLATILITY_WEIGHTING</p>

</details>

<a id="research-e6ac2e50eafcfb07"></a>
<details><summary>PRE2026_CAPACITY_E1_DAILY_SURFACE</summary>

<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>D:\us-tech-quant-results\A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1\capacity_e1_surface.parquet</p>
<p><strong>登记引用：</strong>D:\us-tech-quant-results\A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1\capacity_e1_surface.parquet</p>
<p><strong>旧别名：</strong>PRE2026 CAPACITY E1 DAILY SURFACE</p>
<p><strong>登记别名：</strong>PRE2026 CAPACITY E1 DAILY SURFACE</p>

</details>

<a id="research-937c345d02af39ed"></a>
<details><summary>PRE2026_HISTORICAL_SECURITY_IDENTITY_BRIDGE</summary>

<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>D:\us-tech-quant-results\A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1\security_identity_bridge.parquet</p>
<p><strong>登记引用：</strong>D:\us-tech-quant-results\A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1\security_identity_bridge.parquet</p>
<p><strong>旧别名：</strong>PRE2026 HISTORICAL SECURITY IDENTITY BRIDGE</p>
<p><strong>登记别名：</strong>PRE2026 HISTORICAL SECURITY IDENTITY BRIDGE</p>

</details>

<a id="research-1dfc43ac7521156b"></a>
<details><summary>PRE2026_SECURITY_FACTOR_RISK_SURFACE</summary>

<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>D:\us-tech-quant-results\A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1\security_factor_risk_surface.parquet</p>
<p><strong>登记引用：</strong>D:\us-tech-quant-results\A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1\security_factor_risk_surface.parquet</p>
<p><strong>旧别名：</strong>PRE2026 SECURITY FACTOR RISK SURFACE</p>
<p><strong>登记别名：</strong>PRE2026 SECURITY FACTOR RISK SURFACE</p>

</details>

<a id="research-36af34fb7d40b769"></a>
<details><summary>R6_ATTENUATION_POLICY_VARIANTS</summary>

<p><strong>机制 / 假设：</strong>Change attenuation strength redistribution or tiers around the same R6 signal</p>
<p><strong>旧结论：</strong>Multiplier threshold and capital-destination variants do not create a new mechanism</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>CLOSED_PRIOR_UNCHANGED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_INDIVIDUAL_STOCK_TAIL_RISK_R2/risk_overlay_contract.json</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_INDIVIDUAL_STOCK_TAIL_RISK_R2/risk_overlay_contract.json; D:/us-tech-quant-results/A2_RISK_CONTROL_R5_CONSTANT_GROSS_R6/A2_RISK_CONTROL_R5_CONTRACT.json</p>
<p><strong>旧别名：</strong>R2_MODERATE|R3_TWO_TIER|RISK_CONTROL_R5|INDIVIDUAL_STOCK_TAIL_RISK_R2</p>
<p><strong>登记别名：</strong>INDIVIDUAL_STOCK_TAIL_RISK_R2; R2_MODERATE; R3_TWO_TIER; R6_ATTENUATION_POLICY_VARIANTS; RISK_CONTROL_R5</p>

</details>

<a id="research-2e491f72c480d2d7"></a>
<details><summary>R6_BAD_ASYMMETRY_SIGNAL</summary>

<p><strong>机制 / 假设：</strong>Predict adverse five-session MAE without compensating MFE</p>
<p><strong>旧结论：</strong>R6 is the frozen authoritative loser-risk reference</p>
<p><strong>旧状态：</strong>FORWARD_ACTIVE_WAIT</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_stock_risk_r6.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_STOCK_RISK_R11_PROSPECTIVE/r11_preregistered_evaluation_contract.json; D:/us-tech-quant-results/A2_STOCK_RISK_R6/r6_oof_predictions.parquet; D:/us-tech-quant/scripts/v22/a2_stock_risk_r6.py</p>
<p><strong>旧别名：</strong>A2_RISK_R2|STOCK_RISK_R6|R6_BAD_ASYMMETRY</p>
<p><strong>登记别名：</strong>A2_RISK_R2; R6_BAD_ASYMMETRY; R6_BAD_ASYMMETRY_SIGNAL; STOCK_RISK_R6</p>

</details>

<a id="research-eada1588528fee88"></a>
<details><summary>R6_TOP_DECILE_HALF_CASH_POLICY</summary>

<p><strong>机制 / 假设：</strong>Reduce only high-risk Top20 stock weights</p>
<p><strong>旧结论：</strong>The canonical fixed attenuation policy is already tested and prospectively represented</p>
<p><strong>旧状态：</strong>FORWARD_ACTIVE_WAIT</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_STOCK_RISK_R11_PROSPECTIVE/r11_preregistered_evaluation_contract.json</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_INDIVIDUAL_STOCK_TAIL_RISK_R2/frozen_risk_signal_identity.json; D:/us-tech-quant-results/A2_STOCK_RISK_R11_PROSPECTIVE/r11_preregistered_evaluation_contract.json</p>
<p><strong>旧别名：</strong>R6E|R11_ECONOMIC_SHADOW|R1_MILD</p>
<p><strong>登记别名：</strong>R11_ECONOMIC_SHADOW; R1_MILD; R6E; R6_TOP_DECILE_HALF_CASH_POLICY</p>

</details>

<a id="research-27f0517c6221e16d"></a>
<details><summary>RAW_A2_BROAD_OOF_PREDICTIONS</summary>

<p><strong>机制 / 假设：</strong>Provide historical Raw A2 ranks beyond Top40 from an existing fitted lineage</p>
<p><strong>旧结论：</strong>Existing broad source is sufficient for rank-greater-than-40 provenance; do not rebuild a prediction warehouse</p>
<p><strong>旧状态：</strong>INFRASTRUCTURE_COMPLETE</p>
<p><strong>登记生命周期决策：</strong>KEEP_CORE</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2/oof_predictions.parquet; D:/us-tech-quant/scripts/v22/a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py</p>
<p><strong>旧别名：</strong>A_VS_A2_OOF_FULL_RANKING|PRETOP20_AUTHORITATIVE_POOL</p>
<p><strong>登记别名：</strong>A_VS_A2_OOF_FULL_RANKING; PRETOP20_AUTHORITATIVE_POOL; RAW_A2_BROAD_OOF_PREDICTIONS</p>

</details>

<a id="research-42fe717fbf4a2899"></a>
<details><summary>RAW_A2_HGB_BASELINE</summary>

<p><strong>机制 / 假设：</strong>Frozen Raw A2 control ranking</p>
<p><strong>旧结论：</strong>One frozen model hash and portfolio lineage anchor all later A2 work</p>
<p><strong>旧状态：</strong>INFRASTRUCTURE_COMPLETE</p>
<p><strong>登记生命周期决策：</strong>KEEP_CORE</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2; D:/us-tech-quant/scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py; D:/us-tech-quant-results/RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1/counterfactual_identification_contract.json; D:/us-tech-quant-results/RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1/stock_selection_evidence_matrix.csv; D:/us-tech-quant-results/RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1/raw_a2_identity_verdict.json; D:/us-tech-quant-results/RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1/final_report.md; D:/us-tech-quant-results/RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1/final_validation.json; D:/us-tech-quant-results/RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1/final_independent_review.md</p>
<p><strong>旧别名：</strong>A2_HGB|A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1|AUTHORITATIVE_LEGACY_A2_HGB</p>
<p><strong>登记别名：</strong>A2_HGB; AUTHORITATIVE_LEGACY_A2_HGB; A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1; RAW_A2_HGB_BASELINE</p>

</details>

<a id="research-1b52ba954bc9e114"></a>
<details><summary>RAW_A2_TOP40_CHECKPOINT</summary>

<p><strong>机制 / 假设：</strong>Persist canonical Raw A2 ranks 1 through 40 without a research refit</p>
<p><strong>旧结论：</strong>Canonical fixed-depth membership asset; legacy copies must not replace it</p>
<p><strong>旧状态：</strong>INFRASTRUCTURE_COMPLETE</p>
<p><strong>登记生命周期决策：</strong>KEEP_CORE</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1/checkpoint_contract.json</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1/checkpoint_contract.json; D:/us-tech-quant-results/A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1/raw_a2_top40_membership_checkpoint.parquet</p>
<p><strong>旧别名：</strong>AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1</p>
<p><strong>登记别名：</strong>AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1; RAW_A2_TOP40_CHECKPOINT</p>

</details>

<a id="research-b9bf51dd8b871740"></a>
<details><summary>RAW_SCORE_ACTIVE_DEVIATION_ATTENUATION</summary>

<p><strong>机制 / 假设：</strong>Preserve A2 active deviation only when Raw score predicts right-tail probability</p>
<p><strong>旧结论：</strong>Fixed attenuation is already tested and has its own no-backfill shadow</p>
<p><strong>旧状态：</strong>FORWARD_ACTIVE_WAIT</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_RAW_SCORE_ATTENUATION_PROSPECTIVE_SHADOW_R1/shadow_registration_state.json</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_RAW_SCORE_ACTIVE_DEVIATION_ATTENUATION_R1/final_report.md; D:/us-tech-quant-results/A2_RAW_SCORE_ATTENUATION_PROSPECTIVE_SHADOW_R1/shadow_registration_state.json; D:/us-tech-quant-results/A2_THREE_ARM_POSTFREEZE_FORWARD_R1/forward_contract.json</p>
<p><strong>旧别名：</strong>RAW_SCORE_ATTENUATED_A2_SHADOW_R1</p>
<p><strong>登记别名：</strong>RAW_SCORE_ACTIVE_DEVIATION_ATTENUATION; RAW_SCORE_ATTENUATED_A2_SHADOW_R1</p>

</details>

<a id="research-0fb52d012c8c7e24"></a>
<details><summary>RX_MARGIN_RANGE_EXHAUSTION_LINEAGE</summary>

<p><strong>机制 / 假设：</strong>RX_MARGIN_RANGE_EXHAUSTION_LINEAGE</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>原始引用：</strong>D:\us-tech-quant-results\RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1\frozen_contract.json; D:\us-tech-quant-results\RX_PREACTIVATION_AUTHORITY_REPAIR_R1\price_lineage_recovery\adjusted_prices_pre2026.parquet</p>
<p><strong>登记引用：</strong>D:\us-tech-quant-results\RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1\frozen_contract.json; D:\us-tech-quant-results\RX_PREACTIVATION_AUTHORITY_REPAIR_R1\price_lineage_recovery\adjusted_prices_pre2026.parquet</p>
<p><strong>旧别名：</strong>RANGE_EXHAUSTION; RX_MARGIN_R1; RX_MARGIN_RANGE_EXHAUSTION_LINEAGE</p>
<p><strong>登记别名：</strong>RANGE_EXHAUSTION; RX_MARGIN_R1; RX_MARGIN_RANGE_EXHAUSTION_LINEAGE</p>

</details>

<a id="research-111ce587d33cfa92"></a>
<details><summary>S1_SECTOR_REWEIGHT</summary>

<p><strong>机制 / 假设：</strong>Reduce FF12 concentration while preserving Raw Top20 membership</p>
<p><strong>旧结论：</strong>S1 is the canonical tested sector-reweighting mechanism</p>
<p><strong>旧状态：</strong>FORWARD_ACTIVE_WAIT</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_pit_sector_taxonomy_and_deconcentration_resume_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_THREE_ARM_POSTFREEZE_FORWARD_R1/forward_contract.json; D:/us-tech-quant/scripts/v22/a2_pit_sector_taxonomy_and_deconcentration_resume_r1.py</p>
<p><strong>旧别名：</strong>S1_SOFT_025|PIT_SECTOR_DECONCENTRATION</p>
<p><strong>登记别名：</strong>PIT_SECTOR_DECONCENTRATION; S1_SECTOR_REWEIGHT; S1_SOFT_025</p>

</details>

<a id="research-770176777bcf0bb6"></a>
<details><summary>SECTOR_AWARE_ML_RERANK</summary>

<p><strong>机制 / 假设：</strong>Use sector-relative targets and PIT taxonomy inside an alpha model</p>
<p><strong>旧结论：</strong>Statistically different model but same sector-aware action locus; historical testing is complete</p>
<p><strong>旧状态：</strong>FROZEN_RESEARCH_CANDIDATE</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_sector_aware_ml_and_factor_overnight_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_SECTOR_AWARE_ML_AND_FACTOR_OVERNIGHT_R1/final_report.md; D:/us-tech-quant-results/A2_SECTOR_AWARE_ML_AND_FACTOR_OVERNIGHT_R1/finalist_freeze.json; D:/us-tech-quant/scripts/v22/a2_sector_aware_ml_and_factor_overnight_r1.py</p>
<p><strong>旧别名：</strong>SECTOR_AWARE_RIDGE|FF12_RESIDUAL_S1_TILT</p>
<p><strong>登记别名：</strong>FF12_RESIDUAL_S1_TILT; SECTOR_AWARE_ML_RERANK; SECTOR_AWARE_RIDGE</p>

</details>

<a id="research-f64713885a388f80"></a>
<details><summary>SECTOR_CASH_AND_GROSS_VARIANTS</summary>

<p><strong>机制 / 假设：</strong>Change cash or gross using the same frozen sector concentration state</p>
<p><strong>旧结论：</strong>Alternative cap levels or gross floors are policy-parameter variants; existing fixed forms are already represented</p>
<p><strong>旧状态：</strong>FORWARD_ACTIVE_WAIT</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_concentration_triggered_gross_scaler_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_THREE_ARM_POSTFREEZE_FORWARD_R1/forward_contract.json; D:/us-tech-quant/scripts/v22/a2_concentration_triggered_gross_scaler_r1.py</p>
<p><strong>旧别名：</strong>FIXED_TOP20_DUAL_SECTOR_CASH|CONCENTRATION_TRIGGERED_GROSS_SCALER|SECTOR_CAPS</p>
<p><strong>登记别名：</strong>CONCENTRATION_TRIGGERED_GROSS_SCALER; FIXED_TOP20_DUAL_SECTOR_CASH; SECTOR_CAPS; SECTOR_CASH_AND_GROSS_VARIANTS</p>

</details>

<a id="research-00924ca91c2b6e21"></a>
<details><summary>SEC_FUNDAMENTAL_CHANGE</summary>

<p><strong>机制 / 假设：</strong>Use PIT financial-statement changes as orthogonal alpha</p>
<p><strong>旧结论：</strong>Recovered-coverage research completed once and ended weak or unstable with no promotion</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>CLOSED_PRIOR_UNCHANGED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_pit_sec_fundamental_acceleration_alpha_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_SEC_FUNDAMENTAL_CHANGE_ALPHA_POST_COVERAGE_RECOVERY_R1/final_report.md; D:/us-tech-quant/scripts/v22/a2_pit_sec_fundamental_acceleration_alpha_r1.py</p>
<p><strong>旧别名：</strong>PIT_SEC_FUNDAMENTAL_ACCELERATION_R1|RESUME_R2|SEC_CHANGE_POST_COVERAGE_RECOVERY</p>
<p><strong>登记别名：</strong>PIT_SEC_FUNDAMENTAL_ACCELERATION_R1; RESUME_R2; SEC_CHANGE_POST_COVERAGE_RECOVERY; SEC_FUNDAMENTAL_CHANGE</p>

</details>

<a id="research-e4b0ae696d350949"></a>
<details><summary>SEC_FUNDAMENTAL_CHANGE_R2_WRAPPER</summary>

<p><strong>机制 / 假设：</strong>Resume the already-completed post-coverage SEC branch</p>
<p><strong>旧结论：</strong>Exact task-level duplicate evidence was found; no rerun occurred</p>
<p><strong>旧状态：</strong>CLOSED_DUPLICATE</p>
<p><strong>登记生命周期决策：</strong>TOMBSTONE_EXACT_DUPLICATE</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_EARNINGS_FUNDAMENTAL_CHANGE_ALPHA_R2/final_report.md</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_EARNINGS_FUNDAMENTAL_CHANGE_ALPHA_R2/final_report.md; D:/us-tech-quant-results/A2_EARNINGS_FUNDAMENTAL_CHANGE_ALPHA_R2/hash_manifest.json</p>
<p><strong>旧别名：</strong>A2_EARNINGS_FUNDAMENTAL_CHANGE_ALPHA_R2</p>
<p><strong>登记别名：</strong>A2_EARNINGS_FUNDAMENTAL_CHANGE_ALPHA_R2; SEC_FUNDAMENTAL_CHANGE_R2_WRAPPER</p>

</details>

<a id="research-47397aec42248222"></a>
<details><summary>SIGNAL_HORIZON_AND_PERSISTENCE</summary>

<p><strong>机制 / 假设：</strong>Test whether signal value decays or benefits from holding longer and trading less</p>
<p><strong>旧结论：</strong>Signal persistence and multiple horizons were studied; no pre-existing untouched horizon policy remains</p>
<p><strong>旧状态：</strong>CLOSED_MECHANISM_UNRESOLVED</p>
<p><strong>登记生命周期决策：</strong>PARK_MECHANISM_UNRESOLVED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_RIGHT_TAIL_AND_RANK_DECAY_DIAGNOSTIC_R1/final_report.md</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS/execution_r2_preregistered_contract.json; D:/us-tech-quant-results/A2_RIGHT_TAIL_AND_RANK_DECAY_DIAGNOSTIC_R1/final_report.md</p>
<p><strong>旧别名：</strong>RIGHT_TAIL_RANK_DECAY|HOLD_REPLACE|LONG_HORIZON|REBALANCE_GATE|RANK_PERSISTENCE</p>
<p><strong>登记别名：</strong>HOLD_REPLACE; LONG_HORIZON; RANK_PERSISTENCE; REBALANCE_GATE; RIGHT_TAIL_RANK_DECAY; SIGNAL_HORIZON_AND_PERSISTENCE</p>

</details>

<a id="research-809f18db3991665e"></a>
<details><summary>STOCK_RISK_MODEL_VARIANTS</summary>

<p><strong>机制 / 假设：</strong>Improve prediction of the same stock downside or asymmetry mechanism</p>
<p><strong>旧结论：</strong>R10 explicitly stops new pre-2026 risk-model discovery and freezes R6 as best current signal</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>CLOSED_PRIOR_UNCHANGED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_stock_risk_r10_r11_fast_track.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_STOCK_RISK_R10_CLOSEOUT/r10_freeze_manifest.json; D:/us-tech-quant/scripts/v22/a2_stock_risk_r10_r11_fast_track.py</p>
<p><strong>旧别名：</strong>R3|R3A_R3R|R4|R7|R8|R9|R10</p>
<p><strong>登记别名：</strong>R10; R3; R3A_R3R; R4; R7; R8; R9; STOCK_RISK_MODEL_VARIANTS</p>

</details>

<a id="research-5930d20cd6815a36"></a>
<details><summary>THIRTEEN_F_CHANGE_STANDALONE</summary>

<p><strong>机制 / 假设：</strong>Use institutional holding changes not present in A2 score</p>
<p><strong>旧结论：</strong>Information was present but standalone and score-blend economics were weak</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>CLOSED_PRIOR_UNCHANGED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_13f_institutional_change_alpha_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_13F_INSTITUTIONAL_CHANGE_ALPHA_R1/final_report.md; D:/us-tech-quant/scripts/v22/a2_13f_institutional_change_alpha_r1.py</p>
<p><strong>旧别名：</strong>A2_13F_INSTITUTIONAL_CHANGE_ALPHA_R1</p>
<p><strong>登记别名：</strong>A2_13F_INSTITUTIONAL_CHANGE_ALPHA_R1; THIRTEEN_F_CHANGE_STANDALONE</p>

</details>

<a id="research-c428334cf9603bd5"></a>
<details><summary>THIRTEEN_F_DUAL_SLEEVE</summary>

<p><strong>机制 / 假设：</strong>Diversify Raw A2 with the same 13F change ranking</p>
<p><strong>旧结论：</strong>The fixed sleeve was tested and looked diversifying but was not frozen or admitted; new blend weights are parameter variants</p>
<p><strong>旧状态：</strong>CLOSED_MECHANISM_UNRESOLVED</p>
<p><strong>登记生命周期决策：</strong>UNTESTABLE_TEMPORAL_SOURCE</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_13f_dual_sleeve_diversification_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_13F_DUAL_SLEEVE_DIVERSIFICATION_R1/final_report.md; D:/us-tech-quant/scripts/v22/a2_13f_dual_sleeve_diversification_r1.py</p>
<p><strong>旧别名：</strong>A2_13F_DUAL_SLEEVE_DIVERSIFICATION_R1</p>
<p><strong>登记别名：</strong>A2_13F_DUAL_SLEEVE_DIVERSIFICATION_R1; THIRTEEN_F_DUAL_SLEEVE</p>

</details>

<a id="research-d158fc812313a2e4"></a>
<details><summary>THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE</summary>

<p><strong>机制 / 假设：</strong>13F level and ownership-lifecycle lineage named by the human audit contract</p>
<p><strong>旧结论：</strong>Safe authoritative evidence is insufficient; the component remains unresolved without a negative inference.</p>
<p><strong>登记生命周期决策：</strong>UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE</p>
<p><strong>状态核对：</strong>NO_LEGACY_STATUS</p>
<p><strong>旧别名：</strong>13F_LEVEL; 13F_LIFECYCLE; THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE</p>
<p><strong>登记别名：</strong>13F_LEVEL; 13F_LIFECYCLE; THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE</p>

</details>

<a id="research-0e874ae3a9171b0d"></a>
<details><summary>TOP20_BOUNDARY_RECOVERY_RERANK</summary>

<p><strong>机制 / 假设：</strong>Improve Raw A2 by substituting near-boundary candidates</p>
<p><strong>旧结论：</strong>Same information and action locus already covered by Top60 rerank plus the canonical boundary diagnostic</p>
<p><strong>旧状态：</strong>CLOSED_DUPLICATE</p>
<p><strong>登记生命周期决策：</strong>TOMBSTONE_FUNCTIONAL_REDUNDANCY</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1/final_report.md</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1/final_report.md; D:/us-tech-quant-results/A2_NEXTGEN_TOPK_ENSEMBLE_RERANK_R1/final_report.md</p>
<p><strong>旧别名：</strong>TOP20_BOUNDARY_DIAGNOSTIC|RANK_21_40_RECOVERY|WINNER_INCLUSION</p>
<p><strong>登记别名：</strong>RANK_21_40_RECOVERY; TOP20_BOUNDARY_DIAGNOSTIC; TOP20_BOUNDARY_RECOVERY_RERANK; WINNER_INCLUSION</p>

</details>

<a id="research-c590db10ce57297a"></a>
<details><summary>TOPK_PORTFOLIO_SIZE</summary>

<p><strong>机制 / 假设：</strong>Change concentration by selecting a different number of ranked names</p>
<p><strong>旧结论：</strong>TopK has already been tested; another K is a parameter search rather than a new mechanism</p>
<p><strong>旧状态：</strong>CLOSED_NEGATIVE</p>
<p><strong>登记生命周期决策：</strong>CLOSED_PRIOR_UNCHANGED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/ABCDE_A2_R4_PORTFOLIO_TRANSLATION_USING_HGB_INCUMBENT; D:/us-tech-quant/scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py</p>
<p><strong>旧别名：</strong>TOP5|TOP10|TOP15|TOP20|TOP25|TOP30|TOP40</p>
<p><strong>登记别名：</strong>TOP10; TOP15; TOP20; TOP25; TOP30; TOP40; TOP5; TOPK_PORTFOLIO_SIZE</p>

</details>

<a id="research-5e41d58291b2f671"></a>
<details><summary>UNIFIED_FORWARD_CONTROL_PLANE</summary>

<p><strong>机制 / 假设：</strong>Run frozen Alpha Risk and Execution identities without feedback</p>
<p><strong>旧结论：</strong>One authoritative append-only control plane exists; do not build another ledger or registry</p>
<p><strong>旧状态：</strong>INFRASTRUCTURE_COMPLETE</p>
<p><strong>登记生命周期决策：</strong>KEEP_CORE</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_forward_shadow_unified_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant/config/research_governance/a2_forward_shadow_production_binding_r1.json; D:/us-tech-quant/scripts/v22/a2_forward_shadow_unified_r1.py</p>
<p><strong>旧别名：</strong>A2_FORWARD_SHADOW_UNIFIED_R1|PRODUCTION_BINDING_R1</p>
<p><strong>登记别名：</strong>A2_FORWARD_SHADOW_UNIFIED_R1; PRODUCTION_BINDING_R1; UNIFIED_FORWARD_CONTROL_PLANE</p>

</details>

<a id="research-5c47ba6738d417d0"></a>
<details><summary>WINNER_ORTHOGONAL_LOGISTIC_DIAGNOSTIC</summary>

<p><strong>机制 / 假设：</strong>Ask whether non-A2 PIT features learn the frozen winner label</p>
<p><strong>旧结论：</strong>Same label and information domain but a distinct fixed diagnostic model; no new policy authorization</p>
<p><strong>旧状态：</strong>CLOSED_MECHANISM_UNRESOLVED</p>
<p><strong>登记生命周期决策：</strong>PARK_MECHANISM_UNRESOLVED</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant-results/A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1/final_report.md</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1/final_report.md; D:/us-tech-quant-results/A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1/winner_loser_learnability_recall.csv</p>
<p><strong>旧别名：</strong>CANONICAL_ATTRIBUTION_WINNER_MODEL</p>
<p><strong>登记别名：</strong>CANONICAL_ATTRIBUTION_WINNER_MODEL; WINNER_ORTHOGONAL_LOGISTIC_DIAGNOSTIC</p>

</details>

<a id="research-d3ff2ecd5496ec10"></a>
<details><summary>WINNER_Q90_NEXTGEN_SIGNAL</summary>

<p><strong>机制 / 假设：</strong>Predict the frozen upper tail of multi-horizon QQQ-relative return</p>
<p><strong>旧结论：</strong>Winner-tail hypothesis has been modeled repeatedly and is now represented prospectively</p>
<p><strong>旧状态：</strong>FORWARD_ACTIVE_WAIT</p>
<p><strong>登记生命周期决策：</strong>WAIT_FORWARD</p>
<p><strong>状态核对：</strong>DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED</p>
<p><strong>原始引用：</strong>D:/us-tech-quant/scripts/v22/a2_nextgen_topk_ensemble_rerank_r1.py</p>
<p><strong>登记引用：</strong>D:/us-tech-quant-results/A2_NG8_RISK_R2_TRUE_PROSPECTIVE_FORWARD_CHAIN_R1/forward_contract.json; D:/us-tech-quant/scripts/v22/a2_nextgen_topk_ensemble_rerank_r1.py</p>
<p><strong>旧别名：</strong>Q90|RIDGE_A1|XGB_TAIL|NG8_FIXED_QUANTILE|RAW_SCORE_OOS_TAIL_PREDICTION_R1</p>
<p><strong>登记别名：</strong>NG8_FIXED_QUANTILE; Q90; RAW_SCORE_OOS_TAIL_PREDICTION_R1; RIDGE_A1; WINNER_Q90_NEXTGEN_SIGNAL; XGB_TAIL</p>

</details>

'use strict';
// Fixed UI copy only: backend messages and identifiers are passed through unchanged.
const uiQuery=typeof URLSearchParams!=='undefined'&&typeof location!=='undefined'?new URLSearchParams(location.search):null;
const language=['zh','en','ja'].includes(uiQuery?.get('lang'))?uiQuery.get('lang'):'zh';
const locale={zh:'zh-CN',en:'en-US',ja:'ja-JP'}[language];
const view=['presentation','research'].includes(uiQuery?.get('view'))?uiQuery.get('view'):'research';
const UI_TEXT={
  "仅常规窗口内自动续查，10:20后需单次手动授权":["Automatic checks only within the regular window; one-time manual authorization required after 10:20","自動確認は通常の時間枠内のみ。10:20以降は1回限りの手動承認が必要"],
  "下一新信号起 · 纽约09:55–10:20；当前信号保留原窗口":["From the next new signal · New York 09:55–10:20; the current signal keeps its original window","次の新シグナルから · ニューヨーク09:55–10:20。現在のシグナルは従来の時間枠を維持"],
  "优先窗口":["Priority window","優先時間枠"],
  "剩余目标自动补至当日收盘前10分钟":["Remaining targets continue until 10 minutes before session close","未完了目標は当日の引け10分前まで継続"],
  "等待启动；仅本地纸面记录":["Waiting to start; local paper records only","開始待ち。ローカルのペーパー記録のみ"],
  "策略预算":["Strategy budget","戦略予算"],
  "预算，不代表实际现金":["Budget; not actual cash","予算であり、実際の現金残高ではありません"],
  "历史委托 / 已确认成交":["Historical orders / confirmed fills","過去の注文 / 確認済み約定"],
  "历史记录不代表当前持仓":["Historical records do not establish current positions","過去の記録は現在の保有を示すものではありません"],
  "当前账户资金与持仓尚未核验":["Current account funds and positions are unverified","現在の口座資金・保有は未確認"],
  "目标计划尚未核验":["Target plan is unverified","目標計画は未確認です"],
  "原始状态说明":["Original status details","元の状態説明"],
  "模拟账户 · 实盘执行已锁定":["Simulated account · live execution is locked","シミュレーション口座 · 実取引はロックされています"],
  "补单授权已截止；旧窗口不授予本期补单权限":["Manual authorization expired; the old window does not authorize current-period completion","補完注文の承認は失効しました。過去の時間枠は当期の補完権限を与えません"],
  "历史委托与成交记录":["Historical orders and fills","過去の注文・約定記録"],
  "信号日":["Signal date","シグナル日"],
  "计划进度":["Plan progress","計画の進捗"],
  "本期计划已完成":["Current plan completed","当期計画は完了"],
  "计划待处理":["Plan awaiting processing","計画は処理待ち"],
  "计划状态待核验":["Plan status unverified","計画の状態は未確認"],
  "未完成委托":["Unfinished orders","未完了の注文"],
  "仅统计最近返回的委托":["Latest returned orders only","直近に取得した注文のみ"],
  "目标内未持有":["Target symbols not held: ","目標内の未保有銘柄 "],
  "权重目标与实际持仓是不同口径。执行股数按当时资金、盘口和现金缓冲换算并取整，部分正权重目标可能不足一股；未持有项保留原目标，是否仍需下单以执行记录和券商对账为准。":["Weight targets and actual holdings measure different things. Execution quantities use available funds, quotes and cash buffers, rounded down to whole shares. A positive target may be below one share; unheld targets remain unchanged, and execution records and broker reconciliation determine whether more orders are needed.","目標比率と実際の保有銘柄数は集計基準が異なります。執行株数はその時点の資金・板・現金余裕を基に整数株へ切り捨てるため、正の目標でも1株未満になる場合があります。未保有の目標は維持し、追加注文の要否は執行記録と証券会社との照合で確認します。"],
  "价差":["Spread","スプレッド"],
  "一档最小价差总计":["one-tick spread total","最小呼値の合計スプレッド"],
  "上期补单已完成（信号":["Previous manual completion finished (signal ","前回の補完注文完了（シグナル"],
  "上期计划已执行":["Previous plan executed","前回計画は執行済み"],
  "上期部分执行":["Previous plan partially executed","前回計画は一部執行済み"],
  "上次检查":["Last check","前回の確認"],
  "下一窗口":["Next window","次の時間枠"],
  "两种处理都只在有效执行窗口内进行；待对账不视作成交":["Both actions run only within the valid execution window; pending reconciliation is not a fill","両処理は有効な執行時間内のみ。照合待ちは約定に含みません"],
  "买单确认失败后冷却":["After a confirmed buy-order failure, wait ","買い注文の失敗確認後に待機 "],
  "仅处理原批次尚未完成的目标；每笔成交保留实际时间":["Only unfinished targets in the original batch are processed; actual fill times are retained","元バッチの未完了目標のみ処理し、実際の約定時刻を保存します"],
  "价差超限":["Spread limit exceeded","スプレッド上限超過"],
  "估值至":["Valued at ","評価時刻 "],
  "保持":["Keep","維持"],
  "保留持仓":["Retained positions","保存された保有銘柄"],
  "保留股数":["Retained shares","保存株数"],
  "信号":["Signal ","シグナル "],
  "全部策略":["All strategies","全戦略"],
  "其中已成交":["Confirmed fills","約定確認済み"],
  "其他持仓或目标":["Other positions or targets","その他の保有・目標"],
  "其余策略":["Other strategies","その他の戦略"],
  "冷却剩余":["Cooldown remaining: ","待機残り "],
  "冷却结束":["Cooldown ended","待機終了"],
  "净值":["Equity","純資産"],
  "分钟严格窗口":["minute strict window","分の厳格な時間枠"],
  "分钟优先，剩余目标自动补至当日收盘前":["minutes first; unfinished targets continue until ","分を優先し、未完了目標は当日の引け前まで継続 "],
  "分钟":["minutes","分"],
  "券商同日手动补执行":["Broker same-day manual completion","証券口座の当日手動補完"],
  "券商委托仍需对账；只计入已确认的成交数量，待确认部分不记为成交":["Broker orders still require reconciliation; only confirmed quantities count as fills","証券注文は照合が必要です。確認済み数量のみ約定に計上します"],
  "券商委托号":["Broker order ID ","証券注文番号 "],
  "券商已接收改单":["Amendment acknowledged","訂正受付済み"],
  "券商已接收":["Broker acknowledged","証券会社受付済み"],
  "券商模拟已成交":["Broker simulation filled","証券シミュレーション約定"],
  "券商模拟独立执行规则":["Broker simulation execution rules","証券シミュレーション執行ルール"],
  "券商模拟目标与实际":["Broker simulation targets and actuals","証券シミュレーションの目標と実績"],
  "券商模拟账户":["Broker simulation account","証券シミュレーション口座"],
  "券商模拟":["Broker simulation","証券シミュレーション"],
  "券商状态":["Broker status","証券注文状態"],
  "券商确认失败":["Broker confirmed failure","証券会社が失敗を確認"],
  "剩余现金保留在账户":["Remaining cash stays in the account","残余現金は口座内に保持"],
  "动作":["Action","操作"],
  "单只最多":["Maximum per symbol: ","銘柄ごとの上限 "],
  "历史委托与成交记录保留，不代表当前持仓":["Historical orders and fills are retained; they do not establish current positions","過去の注文・約定を保存しています。現在の保有を示すものではありません"],
  "历史执行检查":["Historical execution checks","過去の執行確認"],
  "历史未成交限价单先对账；间隔":["Reconcile historical unfilled limit orders first; every ","過去の未約定指値注文を先に照合し、間隔 "],
  "历史标价":["Historical mark","過去の評価価格"],
  "历史补单记录":["Historical completion ID ","過去の補完記録 "],
  "历史账户":["Historical account","過去の口座"],
  "历史":["History","履歴"],
  "原券商模拟账户":["Original broker simulation account","元の証券シミュレーション口座"],
  "原模拟账户已绑定":["Original simulation account bound to ","元のシミュレーション口座の連携先 "],
  "原目标现金":["Original target cash","元の現金目標"],
  "原目标记录":["Original target record","元の目標記録"],
  "原计划":["Original plan","元の計画"],
  "原记录没有持仓":["No positions in the original record","元の記録に保有なし"],
  "只仍有持仓":["symbols still held","銘柄を引き続き保有"],
  "只":["symbols","銘柄"],
  "可用内存不足；保留现仓，等待资源恢复后核验新目标":["Insufficient available memory; keep current positions and verify new targets after resources recover","利用可能メモリが不足しています。現在の保有を維持し、回復後に新目標を確認します"],
  "同日手动补执行，数量按实际检查时行情和本账户资金计算":["Same-day manual completion; quantities use quotes and account funds at the actual check time","当日手動補完。確認時点の相場と本口座の資金で株数を計算します"],
  "同日手动补执行":["Same-day manual completion","当日手動補完"],
  "后台状态读取暂忙，当前显示上次成功读取的记录":["Background status read is busy; showing the last successful snapshot","バックグラウンドの読込中です。前回取得成功時の記録を表示しています"],
  "后续买单已另行记录":["A later buy order is recorded separately","後続の買い注文を別途記録済み"],
  "启动模拟盘":["Start simulation","シミュレーション開始"],
  "因子／收缩风险":["Factor / shrinkage risk","ファクター／縮小リスク"],
  "失败后冷却中":["Failure cooldown","失敗後の待機中"],
  "失败后重试规则待核验":["Failure retry rules unverified","失敗後の再試行ルールは未確認"],
  "失败后重试":["Retry after failure","失敗後に再試行"],
  "套独立纸面账户":["independent paper accounts","個の独立ペーパー口座"],
  "委托号":["Order ID","注文番号"],
  "委托股数":["Order shares","注文株数"],
  "完整信号日":["Complete signal date","完全シグナル日"],
  "实际成交以券商对账为准":["Actual fills are confirmed through broker reconciliation","実際の約定は証券会社との照合で確定します"],
  "实际成交以券商确认时间和均价为准":["Actual fills use the broker-confirmed time and average price","実際の約定は証券会社の確認時刻と平均価格に従います"],
  "实际标价最早":["Earliest actual mark ","実際の評価時刻：最古 "],
  "实际现金":["Actual cash","実際の現金"],
  "对角风险":["Diagonal risk","対角リスク"],
  "尚无匹配成交；同日手动补执行以实际成交记录为准":["No matching fills; same-day manual completion follows actual fill records","一致する約定なし。当日手動補完は実際の約定記録に従います"],
  "尚无匹配成交；错过的开盘信号不会补记成交":["No matching fills; missed opening signals are not backfilled as trades","一致する約定なし。逃した寄付シグナルの約定は補記しません"],
  "尚未向券商发送委托":["No orders sent to the broker","証券会社へ送信した注文なし"],
  "尚未完成；后续合格信号在正常执行窗口按当期已冻结目标继续差额调仓":["Incomplete; later qualified signals continue differential rebalancing to the frozen current target in the normal window","未完了。以後の適格シグナルは通常の執行時間に当期の凍結目標との差分を調整します"],
  "尚未尝试改单":["No amendment attempted","訂正の試行なし"],
  "已停止":["Halted","停止済み"],
  "已全部撤销":["Fully cancelled","全取消済み"],
  "已处理":["Processed","処理済み"],
  "已完成；此后恢复当前所选策略的常规调仓":["Complete; regular rebalancing resumes for the selected strategy","完了。現在選択中の戦略の通常リバランスに戻ります"],
  "已就绪":["Ready","準備完了"],
  "已成交":["Filled","約定済み"],
  "已截止":["Expired","期限終了"],
  "已持有":["Held","保有中"],
  "已接收限价":["Acknowledged limit","受付済み指値"],
  "已暂停":["Paused","一時停止中"],
  "已退出活动策略；历史成交可在买卖记录中筛选，完整记录可导出":["Retired from active strategies; filter historical fills in trade records or export the full ","稼働戦略から除外済み。売買履歴で過去の約定を絞り込み、全記録を出力できます "],
  "已部分撤销":["Partially cancelled","一部取消済み"],
  "市价单不改价；以实际成交均价为准":["Market orders are not repriced; actual average fill price applies","成行注文の価格訂正なし。実際の平均約定価格を使用"],
  "市价单":["Market order","成行注文"],
  "常规开盘窗口":["Regular opening window","通常の寄付時間枠"],
  "常规执行规则":["Regular execution rules","通常の執行ルール"],
  "开始。不存在的日期和缺失估值没有补造":[". Missing dates and valuations are not fabricated","から開始。存在しない日付や未取得の評価額は補いません"],
  "开始":["Start","開始"],
  "开盘后":["After open: ","寄付後 "],
  "异常待检查":["Error; check required","異常・確認待ち"],
  "当前下期目标待发布":["Next target has not yet been published","次回目標は未公開"],
  "当前空仓，等待下一完整信号":["No current positions; waiting for the next complete signal","現在は保有なし。次の完全シグナル待ち"],
  "当前账户资金与持仓尚未核验；显示":["Current account funds and positions are unverified; shown as ","現在の口座資金・保有は未確認です。表示は "],
  "当日曾授权补执行，现已截止":["Same-day completion was authorized; the window has expired","当日の補完は承認済みでしたが、現在は期限終了"],
  "待券商确认":["Awaiting broker confirmation","証券会社の確認待ち"],
  "待完整信号":["Awaiting complete signal","完全シグナル待ち"],
  "待执行计算":["Execution calculation pending","執行計算待ち"],
  "待核对限价":["Limit pending confirmation","指値の確認待ち"],
  "待核验；尚无有效的账户转换状态记录":["Unverified; no valid account conversion status record","未確認。有効な口座移行状態記録がありません"],
  "待核验；当前记录缺少可确认的授权窗口或身份":["Unverified; the record lacks a verifiable authorization window or identity","未確認。記録に確認可能な承認時間枠または識別情報がありません"],
  "待核验":["Unverified","未確認"],
  "待确认":["Pending confirmation","確認待ち"],
  "成交时间与价格按实际记录":["Fill times and prices follow actual records","約定時刻・価格は実際の記録に従います"],
  "成交":["Fills","約定"],
  "截止":["Deadline ","期限 "],
  "执行与委托规则":["Execution and order rules","執行・注文ルール"],
  "执行批次待核验":["Execution batch unverified","執行バッチは未確認"],
  "执行检查未通过":["Execution checks failed","執行確認で不合格"],
  "执行检查记录":["Execution check record","執行確認記録"],
  "执行窗口待核验":["Execution window unverified","執行時間枠は未確認"],
  "执行起点待核验":["Execution start unverified","執行開始時刻は未確認"],
  "执行":["Execution ","執行 "],
  "批次日期待核验":["Batch dates unverified","バッチ日付は未確認"],
  "报价待核验":["Quote unverified","気配値は未確認"],
  "持仓已符合":["Target already held","保有は目標と一致"],
  "持仓报价全部通过本次检查":["All position quotes passed this check","保有銘柄の気配値がすべて今回の確認に合格"],
  "持仓转换":["Position conversion","保有移行"],
  "持仓":["Positions","保有"],
  "按各活动账户自己的目标持仓，在计划执行时点检查买卖":["Check trades at the scheduled time against each active account target","予定執行時刻に各稼働口座の目標保有に対して売買を確認します"],
  "按实际成交记录":["Actual fill records apply","実際の約定記録に従います"],
  "按实际持仓和可核验报价计价，各账户按自己的起点从净值":["Valued using actual positions and verifiable quotes; each account starts at NAV ","実際の保有と検証可能な気配値で評価。各口座の開始純資産は "],
  "按新账户的资金和持仓计算目标，旧订单与成交保留在历史记录":["Targets use the new account funds and positions; old orders and fills remain in history","新口座の資金・保有で目標を計算し、過去の注文・約定は履歴に保存します"],
  "按本账户已授权自动接续规则":["Authorized automatic continuation rules for this account","本口座で承認済みの自動継続ルール"],
  "授权有效":["Authorization active","承認は有効"],
  "授权":["Authorized ","承認 "],
  "提交市价单":["submit a market order","成行注文を送信"],
  "提交限价单":["submit a limit order","指値注文を送信"],
  "改单尝试次数":["Amendment attempts","訂正試行回数"],
  "改单待券商核对":["Amendment awaiting broker confirmation","訂正は証券会社の確認待ち"],
  "改单未发送":["Amendment not sent","訂正は未送信"],
  "改单规则待核验":["Amendment rules unverified","訂正ルールは未確認"],
  "数据待更新，当前显示上次成功读取的记录":["Update pending; showing the last successful snapshot","更新待ち。前回取得成功時の記録を表示しています"],
  "数量按计划执行时行情和本账户资金计算":["Quantities use quotes and account funds at the scheduled execution time","予定執行時点の相場と本口座の資金で株数を計算します"],
  "整数股与资金规则产生的余款保留在账户":["Cash remaining after whole-share and funding rules stays in the account","整数株・資金ルールによる残余現金は口座内に保持します"],
  "新买单采用限价单":["New buys use limit orders","新規買いは指値注文"],
  "新买卖单采用市价单；先检查真实盘口、策略现金、可卖库存和股数，券商成交价与成交数量以对账为准":["New buys and sells use market orders after checking actual quotes, strategy cash, sellable inventory and quantities; broker reconciliation confirms fills","新規売買は成行注文。実際の板・戦略資金・売却可能在庫・株数を確認し、価格と数量は証券会社との照合で確定します"],
  "新买单":["New buy orders","新規買い注文"],
  "既有持仓按新目标做差额调整，历史委托与成交保留":["Existing positions rebalance by the target difference; historical orders and fills are retained","既存保有は新目標との差分で調整し、過去の注文・約定を保存します"],
  "日更正在生成最新完整信号，账户等待计划执行时点":["Daily update is preparing the latest complete signal; the account awaits scheduled execution","日次更新で最新の完全シグナルを生成中です。口座は予定執行時刻を待機します"],
  "日本":["Japan","日本"],
  "旧窗口不授予本期补单权限":["The old window does not authorize current-period manual completion","過去の時間枠は当期の補完権限を与えません"],
  "显式退出目标":["Explicit exit targets","明示された退出目標"],
  "显示最近":["Latest ","直近 "],
  "暂无已记录的目标":["No recorded targets","記録された目標なし"],
  "暂时无法连接模拟盘服务；保留上次成功读取的数据，等待更新":["Simulation service is temporarily unreachable; retaining the last successful snapshot","シミュレーションサービスに一時接続できません。前回取得成功時の記録を保持します"],
  "更新收盘数据":["Updating closing data","終値データ更新中"],
  "最晚":["latest ","最新 "],
  "最近券商委托与成交记录":["Recent broker orders and fills","直近の証券注文・約定"],
  "最近委托":["Recent orders","直近注文"],
  "最近成功读取":["Last successful read","最終取得成功"],
  "最近报价":["Latest quote","直近気配値"],
  "有效委托":["Working orders","有効注文"],
  "服务暂时无法提供账户状态，请稍后再核验":["Account status is temporarily unavailable; verify again later","口座状態を一時取得できません。後ほど再確認してください"],
  "服务返回的数据暂未通过核验；保留上次成功读取的数据":["Returned account data is unverified; retaining the last successful snapshot","取得した口座データは未確認です。前回取得成功時の記録を保持します"],
  "未发送限价":["Unsent limit","未送信の指値"],
  "未发送":["Not sent","未送信"],
  "未完成买入的资金仍留在账户":["Funds for unfinished buys remain in the account","未完了の買い資金は口座内に保持します"],
  "未记录的目标保持未知":["Unrecorded targets remain unknown","記録のない目標は不明のまま表示"],
  "未记录":["Not recorded","記録なし"],
  "本期执行未成交":["Current execution had no fills","当期執行は約定なし"],
  "本期执行窗口已结束，不再自动重试":["Current execution window ended; no more automatic retries","当期の執行時間は終了しました。自動再試行は行いません"],
  "本期目标待执行":["Current target awaits execution","当期目標は執行待ち"],
  "本期行情检查未通过项":["Current quote check failures","当期の気配値確認の不合格項目"],
  "本期计划已执行":["Current plan executed","当期計画は執行済み"],
  "本期部分执行":["Current plan partially executed","当期計画は一部執行済み"],
  "本次合格":["Qualified this check: ","今回適格 "],
  "本次手动补单":["Current manual completion","今回の手動補完"],
  "本次未更新净值":["NAV not updated this check","今回の純資産は未更新"],
  "本次补单已执行":["Current manual completion executed","今回の補完は執行済み"],
  "本策略模拟本金":["Strategy simulation capital","本戦略のシミュレーション元本"],
  "本记录不代表本期执行状态":["This record does not establish current execution status","本記録は当期の執行状態を示しません"],
  "本账户已授权自动接续":["Automatic continuation authorized for this account","本口座は自動継続を承認済み"],
  "本页按接口返回范围显示最近":["This page shows the latest ","本画面はAPI返却範囲の直近 "],
  "本页最近":["Latest on this page: ","本画面の直近 "],
  "权重差":["Weight difference","比率差"],
  "标价时间":["Mark time ","評価時刻 "],
  "检查未通过":["Check failed","確認で不合格"],
  "检查":["Check","確認"],
  "模拟盘":["Simulation","シミュレーション"],
  "模拟账户":["Simulation account","シミュレーション口座"],
  "次。市价单不改价":["attempts. Market orders are not repriced","回。成行注文の価格訂正なし"],
  "次":["attempts","回"],
  "正在核验，当前显示上次成功读取的记录":["Verifying; showing the last successful snapshot","確認中。前回取得成功時の記録を表示しています"],
  "正在读取账户状态":["Reading account status","口座状態を取得中"],
  "此处显示原行情检查记录；完整计划与已返回的持仓范围见上方目标、退出及其他持仓表":["Original quote checks are shown here; see the target, exit and other-position tables above for the full plan and returned positions","元の相場確認記録です。計画全体と取得済み保有は上の目標・退出・その他の保有表を参照してください"],
  "每日自动接续":["Daily automatic continuation","日次の自動継続"],
  "活动策略":["Active strategies","稼働中の戦略"],
  "活动纸面账户的实际净值路径":["Actual NAV paths of active paper accounts","稼働ペーパー口座の実際の純資産推移"],
  "活动账户尚未初始化":["Active accounts have not been initialized","稼働口座は未初期化"],
  "混合标价":["Mixed marks","混合評価価格"],
  "状态待确认":["Status unconfirmed","状態は未確認"],
  "独立纸面账户":["Independent paper accounts","独立ペーパー口座"],
  "独立账户各":["Each independent account: ","独立口座ごとに "],
  "独立资金与成交记录":["Independent funds and fill records","独立した資金・約定記録"],
  "现仓权重。实际执行股数由执行时的账户资金与合格盘口确定":["current weight. Execution quantities depend on account funds and qualified quotes at execution","現在比率。実際の執行株数は執行時の口座資金と適格な板情報で決まります"],
  "现仓权重按券商返回的持仓市值计算，未记录市值的权重及差值保持未知；权重差":["Current weights use broker-reported position values; missing values leave weights and differences unknown. Weight difference ","保有比率は証券会社の時価で計算します。時価未取得の比率と差分は不明です。比率差 "],
  "现仓权重":["Current weight","現在比率"],
  "现有股数":["Current shares","現在株数"],
  "现金":["Cash","現金"],
  "目标、现仓与权重差":["Target, current and weight difference","目標・現在保有・比率差"],
  "目标内持有":["Held within target: ","目標内保有 "],
  "目标外剩余":["Held outside target: ","目標外保有 "],
  "目标持仓":["Target positions","目標保有"],
  "目标权重":["Target weight","目標比率"],
  "目标现金":["Target cash","目標現金"],
  "目标股票":["Target stocks","目標銘柄"],
  "真实记录时间":["Actual record times","実際の記録時刻"],
  "确认失败":["Confirmed failure","確認済み失敗"],
  "确认成交均价":["Confirmed average fill price","確認済み平均約定価格"],
  "确认成交股数":["Confirmed fill shares","確認済み約定株数"],
  "秒沿用原券商委托号改单，单笔最多":["seconds, amend the same broker order ID; maximum ","秒で同じ証券注文番号を訂正し、注文ごとの上限 "],
  "秒，再核验最新报价及剩余量，以新客户端标识":["seconds, then recheck quotes and remaining quantity and use a new client ID to ","秒後に最新気配値と残数量を再確認し、新しいクライアントIDで "],
  "秒；保留上次成功读取的数据，等待下一次核验":["seconds; retaining the last successful snapshot until the next check","秒超。前回取得成功時の記録を保持し、次の確認を待機します"],
  "秒":["seconds","秒"],
  "窗口待核验":["Window unverified","時間枠は未確認"],
  "笔委托；原账户完整历史保留在账本中":["orders returned by the API; full account history remains in the ledger","件の注文を表示。元口座の全履歴は台帳に保存しています"],
  "笔待确认":["pending confirmation","件は確認待ち"],
  "笔":["records","件"],
  "等待券商对账":["Awaiting broker reconciliation","証券会社との照合待ち"],
  "等待合格报价":["Awaiting qualified quotes","適格な気配値待ち"],
  "等待实际成交与行情计价记录":["awaiting actual fills and quote valuations","実際の約定・相場評価記録を待機中"],
  "等待执行窗口":["Awaiting execution window","執行時間枠待ち"],
  "等待收盘信号":["Awaiting close signal","終値シグナル待ち"],
  "等待数据源核验":["Awaiting source verification","データソース確認待ち"],
  "等待最新合格卖一价":["Awaiting a fresh qualified ask","新しい適格な最良売気配待ち"],
  "等待最新盘口":["Awaiting latest quotes","最新の板情報待ち"],
  "等待每日手动更新":["Awaiting daily manual update","日次手動更新待ち"],
  "等待第一笔开盘成交与行情计价记录":["awaiting the first opening fill and quote valuation","最初の寄付約定・相場評価記録を待機中"],
  "等待计划执行时点；自动买卖仅限此模拟账户":["Awaiting scheduled execution; automatic trading is limited to this simulation account","予定執行時刻待ち。自動売買はこのシミュレーション口座に限定します"],
  "等待计划执行":["Awaiting scheduled execution","予定執行待ち"],
  "等待":["Waiting","待機"],
  "策略净值":["Strategy equity","戦略純資産"],
  "策略待核验":["Strategy unverified","戦略は未確認"],
  "策略模拟持仓市值":["Strategy simulation position value","戦略のシミュレーション保有時価"],
  "策略现金":["Strategy cash","戦略現金"],
  "纸面成交":["Paper fill","ペーパー約定"],
  "纸面账户净值":["Paper account NAV","ペーパー口座純資産"],
  "纸面账户待初始化":["Paper accounts await initialization","ペーパー口座は初期化待ち"],
  "纽约":["New York","ニューヨーク"],
  "组合报价全部合格后执行":["Execute after all portfolio quotes qualify","ポートフォリオ全体の気配値が適格になってから執行"],
  "缺口":["Gaps","不足"],
  "缺少真实标价":["Missing actual marks","実際の評価価格が未取得"],
  "美东时间":["US Eastern time","米国東部時間"],
  "美东":["US Eastern","米国東部"],
  "股票":["Symbol","銘柄"],
  "自动执行已停止；当前不会改单或失败后重试，也不会补下旧信号":["Automatic execution is halted; no amendments, failure retries or backfilled old signals","自動執行は停止済み。訂正・失敗後の再試行・過去シグナルの補完は行いません"],
  "自动执行暂停；当前不会改单或失败后重试":["Automatic execution paused; no amendments or failure retries","自動執行は一時停止中。訂正や失敗後の再試行は行いません"],
  "自动执行暂停":["Automatic execution paused","自動執行は一時停止中"],
  "行情不合格":["Quote check failed","気配値の確認で不合格"],
  "行情待核验":["Quotes unverified","相場は未確認"],
  "补单记录":["Completion ID ","補完記録 "],
  "补执行授权时点尚未到达":["Completion authorization has not started","補完の承認開始時刻前"],
  "补执行授权窗口内":["Within the authorized completion window","承認済みの補完時間枠内"],
  "观测":["Observed ","観測 "],
  "计划意图":["Planned intent","計画上の意図"],
  "记录时间":["Record time","記録時刻"],
  "记录重试时点":["Recorded retry time ","記録された再試行時刻 "],
  "账户总余额由券商预设；本策略独立核算原模拟本金、持仓与成交":["MOOMOO sets the account-wide balance; this strategy separately accounts for its original simulation capital, positions and fills","MOOMOO口座全体の残高は証券会社が設定。本戦略の元本・保有・約定は独立して計算します"],
  "账户待核验":["Account unverified","口座は未確認"],
  "账户状态已成功读取":["Account status read successfully","口座状態の取得に成功"],
  "账户状态待核验；连接恢复后再更新":["Account status unverified; updates resume after reconnection","口座状態は未確認。接続回復後に更新します"],
  "账户状态暂时无法核验；保留上次成功读取的数据":["Account status cannot be verified now; retaining the last successful snapshot","口座状態を一時確認できません。前回取得成功時の記録を保持します"],
  "账户状态读取超过":["Account status read exceeded ","口座状態の読込が "],
  "账户":["Account","口座"],
  "账本更新":["Ledger updated ","台帳更新 "],
  "资金不足":["Insufficient funds","資金不足"],
  "资金限制":["Funding limit","資金制限"],
  "起始净值":["Starting NAV","開始純資産"],
  "起生效":["effective from","より適用"],
  "跳过":["Skipped","スキップ"],
  "运行中":["Running","稼働中"],
  "退出目标":["Exit targets","退出目標"],
  "逐股检查，异常跳过留现金":["Check each symbol; skip failures and retain cash","銘柄ごとに確認し、異常時はスキップして現金を保持"],
  "通常":["Usually","通常"],
  "部分成交":["Partially filled","一部約定"],
  "重置后的模拟账户已接入":["Reset simulation account connected to ","リセット後のシミュレーション口座の接続先 "],
  "限价单":["Limit order","指値注文"],
  "暂停":["Pause","一時停止"],
  "停止买卖":["Halt trading","売買停止"],
  "刷新":["Refresh","更新"],
  "正在读取券商模拟与纸面账户":["Reading broker simulation and paper accounts","証券シミュレーション・ペーパー口座を取得中"],
  "账户区导航":["Account navigation","口座ナビゲーション"],
  "正在读取原券商模拟账户":["Reading the original broker simulation account","元の証券シミュレーション口座を取得中"],
  "纸面总览":["Paper overview","ペーパー口座概要"],
  "成交记录":["Fill history","約定履歴"],
  "独立账本":["Independent ledgers","独立台帳"],
  "各账户自己的现金、持仓与成交":["Each account has its own cash, positions and fills","各口座で現金・保有・約定を独立管理"],
  "执行时钟":["Execution clock","執行時刻"],
  "运行状态":["Run status","稼働状態"],
  "连接中":["Connecting","接続中"],
  "本期计划":["Current plan","当期計画"],
  "行情来源":["Quote source","相場ソース"],
  "正在读取活动策略账户":["Reading active strategy accounts","稼働戦略の口座を取得中"],
  "纸面账户执行规则":["Paper account execution rules","ペーパー口座の執行ルール"],
  "正在读取执行规则":["Reading execution rules","執行ルールを取得中"],
  "账户对比":["Account comparison","口座比較"],
  "策略":["Strategy","戦略"],
  "状态":["Status","状態"],
  "累计净收益":["Cumulative net return","累積純収益率"],
  "最大回撤":["Maximum drawdown","最大ドローダウン"],
  "持仓数":["Positions","保有銘柄数"],
  "累计费用":["Total fees","累積費用"],
  "成交笔数":["Fill count","約定件数"],
  "读取中":["Loading","読込中"],
  "净值按实际持仓和可核验行情计价。买入按卖一价、卖出按买一价纸面撮合，单边成本":["Equity uses actual positions and verifiable quotes. Paper buys match at ask and sells at bid, with one-way costs of ","純資産は実際の保有と検証可能な相場で評価。買いは最良売気配、売りは最良買気配でペーパー約定し、片道コストは "],
  "整数股取整后的现金保留在各账户":["Cash left after whole-share rounding stays in each account","整数株への丸め後の現金は各口座に保持"],
  "净值路径":["NAV path","純資産推移"],
  "各账户自己的起点":["Each account starts at","各口座の開始値"],
  "实际记录时间":["Actual record time","実際の記録時刻"],
  "成交后开始记录净值路径":["NAV recording starts after fills","約定後に純資産推移の記録を開始"],
  "活动账户持仓与动作":["Active account positions and actions","稼働口座の保有・操作"],
  "买卖记录":["Trade records","売買履歴"],
  "行情驱动的本地纸面成交":["quote-driven local paper fills","相場を用いたローカルのペーパー約定"],
  "代码，如":["Symbol, e.g.","銘柄コード、例"],
  "导出全部":["Export all","全件出力"],
  "成交股数":["Fill shares","約定株数"],
  "成交价":["Fill price","約定価格"],
  "费用":["Fees","費用"],
  "尚无成交记录":["No fills recorded","約定記録なし"],
  "最近记录":["Recent records","直近記録"],
  "包含全部历史成交":["contains all historical fills","には全約定履歴を含みます"],
  "退出活动的策略历史":["Retired strategy history","稼働終了した戦略の履歴"],
  "原持仓、现金与成交记录保留":["Original positions, cash and fill records are retained","元の保有・現金・約定記録を保存"],
  "本地独立纸面账本":["Local independent paper ledgers","ローカルの独立ペーパー台帳"],
  "虚拟资金":["Virtual funds","仮想資金"],
  "实际行情时间保留在成交记录中":["Actual quote times are retained in fill records","実際の相場時刻は約定記録に保存"],
  "手动模拟工作台":["Manual simulation workspace","手動シミュレーション画面"],
  "五策略":["Five strategies","5戦略"]
};
const UI_PATTERN=new RegExp(Object.keys(UI_TEXT).sort((a,b)=>b.length-a.length).map(key=>Array.from(key,c=>'\\^$.*+?()[]{}|'.includes(c)?String.fromCharCode(92)+c:c).join('')).join('|'),'g');
function ui(parts,...values){
  const fixed=text=>{if(language==='zh')return text;const copy=text.replace(UI_PATTERN,key=>UI_TEXT[key][language==='en'?0:1]);return language==='en'?copy.replace(/[。；，、：（）]/g,c=>({'。':'.','；':'; ','，':', ','、':', ','：':': ','（':'(', '）':')'}[c])):copy;};
  if(typeof parts==='string')return fixed(parts);
  return parts.reduce((result,part,index)=>result+fixed(part)+(index<values.length?values[index]:''),'');
}
function initializeLanguage(){
  if(document.documentElement)document.documentElement.lang=locale;
  document.title=ui('模拟盘 · 五策略');
  document.querySelectorAll('[data-ui]').forEach(node=>{node.textContent=ui(node.textContent);});
  for(const attribute of ['aria-label','placeholder'])document.querySelectorAll('['+attribute+']').forEach(node=>{node.setAttribute(attribute,ui(node.getAttribute(attribute)));});
  document.body?.classList?.toggle('embedded',uiQuery?.get('embed')==='1');
  document.body?.classList?.toggle('presentation',view==='presentation');
}
const names={RAW_A2:'Raw A2',HGB_DIAG_5:ui('HGB＋对角风险'),HGB_FACTOR_5:ui('HGB＋因子／收缩风险'),R10_DIRECT_MEAN4_ELASTICNET_MID:'ElasticNet MID',R10_DIRECT_H5_RIDGE_MID:'Ridge H5 MID',R7_GROSS_LINEAR:'R7 LINEAR'};
const colors={RAW_A2:'#2357d9',HGB_DIAG_5:'#d97706',HGB_FACTOR_5:'#087f71',R10_DIRECT_MEAN4_ELASTICNET_MID:'#087f71',R10_DIRECT_H5_RIDGE_MID:'#7c3aed',R7_GROSS_LINEAR:'#c03b65'};
const states={WAITING_SOURCE:ui('等待数据源核验'),WAITING_MANUAL_UPDATE:ui('等待每日手动更新'),REFRESHING:ui('更新收盘数据'),WAITING_CLOSE:ui('等待收盘信号'),WAITING_OPEN:ui('等待计划执行'),TARGET_ONLY:ui('本期目标待执行'),MISSED_OPEN:ui('本期执行未成交'),WAITING_QUOTES:ui('等待合格报价'),PARTIALLY_EXECUTED:ui('本期部分执行'),CANCELLED_BEFORE_SEND:ui('未发送 · 检查未通过'),READY:ui('已就绪'),RUNNING:ui('运行中'),STOPPED:ui('已暂停'),HALTED:ui('已停止'),BLOCKED:ui('执行检查未通过'),ERROR:ui('异常待检查'),EXECUTED:ui('本期计划已执行'),FILLED:ui('纸面成交'),FILLED_ALL:ui('券商模拟已成交'),FILLED_PART:ui('部分成交'),SUBMITTED:ui('券商已接收'),PENDING_RECONCILE:ui('等待券商对账'),UNKNOWN:ui('状态待确认'),ATTEMPTING:ui('改单待券商核对'),NOT_SENT:ui('改单未发送'),ACKNOWLEDGED:ui('券商已接收改单')};
Object.assign(states,{FAILED:ui('券商确认失败'),CANCELLED_ALL:ui('已全部撤销'),CANCELLED_PART:ui('已部分撤销'),RETRY_COOLDOWN:ui('失败后冷却中')});
const notes=(reason,last)=>{const shown=value=>value==='CONSENSUS_RESOURCE_FLOOR'?ui('可用内存不足；保留现仓，等待资源恢复后核验新目标。'):value==='等待启动；仅本地纸面记录'?ui('等待启动；仅本地纸面记录'):value;return [shown(reason),last&&last!==reason?ui('上次检查：')+shown(last):''].filter(Boolean).join(' · ');};
const REFRESH_INTERVAL_MS=15000,GET_TIMEOUT_MS=15000,STALE_AFTER_MS=30000;
let snapshot=null,token=null,busy=false,activeOperations=0;
let refreshFlight=null,refreshQueued=false,refreshGeneration=0,pollTimer=null;
let lastSuccessAt=0,lastReadFailed=false,refreshLoading=false;
const $=id=>document.getElementById(id);
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,d=2)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const pct=v=>typeof v==='number'&&Number.isFinite(v)?`${v>=0?'+':''}${num(v*100,2)}%`:'—';
const ny=v=>{if(!v)return '—';const date=new Date(v);return Number.isFinite(date.getTime())?new Intl.DateTimeFormat(locale,{timeZone:'America/New_York',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(date):String(v)};
const label=v=>states[v]||v||'—';
const list=v=>Array.isArray(v)?v:(v&&typeof v==='object'?Object.entries(v).map(([k,item])=>typeof item==='object'?{code:k,...item}:{code:k,qty:item}):[]);
async function api(path,body){
  const opt={cache:'no-store'};
  if(body!==undefined){if(!token)token=(await api('/api/token')).token;Object.assign(opt,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(body)});}
  const controller=body===undefined?new AbortController():null;
  const timer=controller?setTimeout(()=>controller.abort(),GET_TIMEOUT_MS):null;
  if(controller)opt.signal=controller.signal;
  let response=null;
  try{
    response=await fetch(path,opt);
    const result=await response.json();
    if(!response.ok||result?.ok!==true)throw new Error(result?.error||`HTTP ${response.status}`);
    return path==='/api/applied/view'&&result.display
      ?{...result.data,display_snapshot:result.display}:result.data;
  }catch(e){
    if(!controller)throw e;
    if(controller.signal.aborted)throw new Error(ui('账户状态读取超过 15 秒；保留上次成功读取的数据，等待下一次核验。'));
    if(response&&!response.ok)throw new Error(ui('服务暂时无法提供账户状态，请稍后再核验。'));
    if(response)throw new Error(ui('服务返回的数据暂未通过核验；保留上次成功读取的数据。'));
    throw new Error(ui('暂时无法连接模拟盘服务；保留上次成功读取的数据，等待更新。'));
  }finally{if(timer!==null)clearTimeout(timer);}
}
function error(message){$('error').hidden=!message;$('error').textContent=message||'';}
function renderControls(now=Date.now()){
  const s=snapshot,stale=!s||!lastSuccessAt||lastReadFailed||now-lastSuccessAt>=STALE_AFTER_MS;
  $('start').disabled=busy||stale||!!s?.running||!!s?.halted||!!(s?.broker&&!accountSnapshotKnown(s.broker));
  $('stop').disabled=busy||!s?.running;
  $('halt').disabled=!s||!!s.halted;
}
function renderReadFreshness(now=Date.now()){
  renderControls(now);
  const host=$('snapshot-sync');if(!host)return;
  if(!lastSuccessAt){const text=refreshLoading?ui('正在读取账户状态…'):ui('账户状态待核验；连接恢复后再更新。');if(host.textContent!==text)host.textContent=text;host.className='binding-note';return;}
  const stale=lastReadFailed||now-lastSuccessAt>=STALE_AFTER_MS;
  const state=stale?(snapshot?.display_snapshot?.owner_busy?ui('后台状态读取暂忙，当前显示上次成功读取的记录'):ui('数据待更新，当前显示上次成功读取的记录')):refreshLoading?ui('正在核验，当前显示上次成功读取的记录'):ui('账户状态已成功读取');
  const text=ui`最近成功读取 · 美东 ${ny(new Date(lastSuccessAt).toISOString())} · ${state}`;
  if(host.textContent!==text)host.textContent=text;
  host.className='binding-note'+(stale?' negative':'');
}
function bookRows(s){return Array.isArray(s.books)?s.books:Object.values(s.books||{});}
function legacyBooks(s){const books=s.legacy_history?.books||{};return Array.isArray(books)?books:Object.values(books);}
function strategyLabel(id,book){return Object.prototype.hasOwnProperty.call(names,id)?names[id]:book?.name||id;}
function stateTone(value){
  return ['ERROR','HALTED','BLOCKED','FAILED','CANCELLED_BEFORE_SEND'].includes(value)?'negative':
    ['EXECUTED','FILLED','FILLED_ALL','READY'].includes(value)?'positive':
    ['WAITING_SOURCE','REFRESHING','WAITING_CLOSE','WAITING_OPEN','WAITING_QUOTES','PARTIALLY_EXECUTED','FILLED_PART','SUBMITTED','PENDING_RECONCILE','UNKNOWN','MISSED_OPEN'].includes(value)?'waiting':'neutral';
}
function statusPill(value,text=label(value)){return `<span class="pill tone-${stateTone(value)}">${esc(text)}</span>`;}
function metric(title,value,detail){return `<div class="account-metric"><span>${esc(title)}</span><strong>${value}</strong><small>${detail}</small></div>`;}
function recordCode(row){return row.code|| (row.ticker?'US.'+row.ticker:'');}
function accountSnapshotKnown(book){
  const positions=book.positions??book.account?.positions;
  const cash=book.cash??book.strategy_cash??book.account?.cash;
  const equity=book.equity??book.strategy_equity??book.account?.equity;
  return positions!==null&&positions!==undefined&&typeof positions==='object'&&
    typeof cash==='number'&&Number.isFinite(cash)&&typeof equity==='number'&&Number.isFinite(equity);
}
function positionTargetRows(book){
  const rawPositions=book.positions??book.account?.positions,known=accountSnapshotKnown(book);
  const positions=new Map(list(rawPositions).map(row=>[recordCode(row),row]));
  const rows=list(book.plan?.rows||book.plan?.targets),keys=new Set(rows.map(recordCode));
  const result=rows.map(row=>{
    const code=recordCode(row),position=positions.get(code),qty=position?.qty??(known?0:null);
    const value=position?.market_value;
    const weight=typeof value==='number'&&Number.isFinite(value)&&typeof book.equity==='number'&&book.equity>0?value/book.equity:null;
    return {...row,code,current_qty:qty,current_weight:weight};
  });
  for(const [code,position] of positions)if(position.qty>0&&!keys.has(code))result.push({code,current_qty:position.qty,target_weight:null,current_weight:null,action:null});
  return result;
}
function brokerTargetTable(rows,id){
  return ui`<div id="${esc(id)}" class="table-wrap target-table"><table><thead><tr><th scope="col">股票</th><th scope="col">现有股数</th><th scope="col">现仓权重</th><th scope="col">目标权重</th><th scope="col">权重差</th><th scope="col">计划意图</th></tr></thead><tbody>${rows.map(row=>{
    const target=typeof row.target_weight==='number'&&Number.isFinite(row.target_weight)?row.target_weight:null;
    const difference=target!==null&&row.current_weight!==null?target-row.current_weight:null;
    const action=row.action||row.side,actionText=action==='SELL'&&target===0?ui('SELL · 退出目标'):action==='BUY'?ui('BUY · 目标持仓'):action==='HOLD'?ui('HOLD · 保持'):action||ui('未记录');
    return `<tr><td class="stock-code">${esc(String(row.code).replace(/^US\./,''))}</td><td>${num(row.current_qty,0)}</td><td>${row.current_weight!==null?num(row.current_weight*100,2)+'%':'—'}</td><td>${target!==null?num(target*100,2)+'%':'—'}</td><td>${pct(difference)}</td><td>${esc(actionText)}</td></tr>`;
  }).join('')||ui('<tr><td colspan="6" class="empty">暂无已记录的目标</td></tr>')}</tbody></table></div>`;
}
function renderMembership(s,books){
  const count=books.length||list(s.strategies).length;
  $('workspace-title').textContent=ui('模拟盘');
  $('workspace-subtitle').textContent=(s.broker?strategyLabel(s.broker.strategy_id,s.broker)+ui(' · 原券商模拟账户 · '):'')+(count?ui`${count} 套独立纸面账户`:ui('纸面账户待初始化'));
  $('paper-heading').textContent=count?ui`${count} 套独立纸面账户`:ui('独立纸面账户');
  $('start').textContent=ui('启动模拟盘');
  $('strategy-legend').innerHTML=books.map(b=>`<span style="color:${colors[b.strategy_id]||'#25312c'}">● ${esc(strategyLabel(b.strategy_id,b))}</span>`).join('');
  const retired=legacyBooks(s),retiredIds=new Set(retired.map(b=>b.strategy_id));
  const ids=[...new Set([...books.map(b=>b.strategy_id),...retiredIds,...list(s.trades).map(t=>t.strategy_id)].filter(Boolean))];
  const select=$('trade-strategy'),selected=select.value;
  select.innerHTML=ui('<option value="">全部策略 / 历史</option>')+ids.map(id=>`<option value="${esc(id)}">${esc(strategyLabel(id,books.find(b=>b.strategy_id===id)||retired.find(b=>b.strategy_id===id)))}${retiredIds.has(id)?ui(' · 历史'):''}</option>`).join('');
  select.value=ids.includes(selected)?selected:'';
  $('legacy-panel').hidden=!retired.length;
  $('legacy-books').innerHTML=retired.map(b=>ui`<article class="legacy-book"><h3>${esc(strategyLabel(b.strategy_id,b))} · 历史账户</h3><p>账户 ${esc(b.account_id)} · 现金 $${num(b.cash)} · 净值 $${num(b.equity)} · 持仓 ${list(b.positions).filter(p=>p.qty>0).length} · 成交 ${num(b.trade_count??b.fills_count??list(b.trades).length,0)}</p><p class="note">已退出活动策略；历史成交可在买卖记录中筛选，完整记录可导出 CSV。</p><details><summary>保留持仓</summary><div class="table-wrap"><table><thead><tr><th>股票</th><th>保留股数</th><th>历史标价</th></tr></thead><tbody>${list(b.positions).filter(p=>p.qty>0).map(p=>`<tr><td>${esc(String(p.code||p.ticker).replace(/^US\./,''))}</td><td>${num(p.qty,0)}</td><td>${num(p.mark_price??p.price,4)}</td></tr>`).join('')||ui('<tr><td colspan="3" class="empty">原记录没有持仓</td></tr>')}</tbody></table></div></details></article>`).join('');
}
function paperCatchup(s){
  const signal=s.signal_date||s.meta?.signal_date||s.source?.signal_date,execution=s.execution_date||s.meta?.execution_date||s.source?.execution_date;
  if(!signal||!execution)return null;
  const records=[s.paper_same_day_catchup,s.meta?.paper_same_day_catchup,...bookRows(s).map(b=>b.paper_same_day_catchup)];
  return records.find(r=>r&&typeof r==='object'&&r.signal_date===signal&&r.execution_date===execution&&
    typeof r.authorized_at_utc==='string'&&typeof r.deadline_utc==='string'&&
    /(?:Z|[+-]\d{2}:\d{2})$/.test(r.authorized_at_utc)&&/(?:Z|[+-]\d{2}:\d{2})$/.test(r.deadline_utc)&&
    Number.isFinite(Date.parse(r.authorized_at_utc))&&Number.isFinite(Date.parse(r.deadline_utc))&&
    Date.parse(r.deadline_utc)>Date.parse(r.authorized_at_utc))||null;
}
function catchupNote(s,now=Date.now()){
  const r=paperCatchup(s);if(!r)return '';
  const state=now>=Date.parse(r.deadline_utc)?ui('当日曾授权补执行，现已截止'):now<Date.parse(r.authorized_at_utc)?ui('补执行授权时点尚未到达'):ui('补执行授权窗口内');
  return ui`同日手动补执行 · 授权 ${ny(r.authorized_at_utc)} · 截止 ${ny(r.deadline_utc)}（纽约 / 美东时间） · ${state}；成交时间与价格按实际记录。`;
}
function activeBookRows(s){
  const membership=s.strategies?new Set(list(s.strategies).filter(row=>row.active===true).map(row=>row.strategy_id)):null;
  return bookRows(s).filter(b=>b.paused!==true&&b.status!=='PAUSED'&&(!membership||membership.has(b.strategy_id)));
}
function automaticPolicyIds(s){
  const p=s.automatic_completion_policy;
  if(p?.enabled!==true||!Array.isArray(p.active_strategy_ids))return new Set();
  const active=new Set(activeBookRows(s).map(b=>b.strategy_id));
  return new Set(p.active_strategy_ids.filter(id=>active.has(id)));
}
function automaticCompletionNote(s,strategyId){
  const ids=automaticPolicyIds(s);
  if(!ids.size||(strategyId&&!ids.has(strategyId)))return '';
  const p=s.automatic_completion_policy,scope=activeBookRows(s).filter(b=>ids.has(b.strategy_id)).map(b=>strategyLabel(b.strategy_id,b)).join('、');
  return ui`${scope} · 每日自动接续 · ${p.effective_execution_date} 起生效 · 优先窗口 ${strictWindow(s)} · ${p.schema_version===2?ui('仅常规窗口内自动续查，10:20后需单次手动授权'):ui('剩余目标自动补至当日收盘前10分钟')} · ${p.one_tick_spread?ui('通常≤50bp，一档最小价差总计≤200bp'):ui('价差≤50bp')} · 按实际成交记录`;
}
function strictWindow(s){
  const delay=s.execution_delay_minutes,seconds=s.execution_window_seconds;
  if(typeof delay==='number'&&Number.isFinite(delay)&&typeof seconds==='number'&&Number.isFinite(seconds))return ui`开盘后 ${num(delay,0)}–${num(delay+seconds/60,seconds%60?1:0)} 分钟严格窗口`;
  const date=new Date(s.execution_time_utc||s.next_expected_execution_utc||'');
  const start=Number.isFinite(date.getTime())?ui('美东 ')+new Intl.DateTimeFormat(locale,{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hour12:false}).format(date)+ui(' 开始'):ui('执行起点待核验');
  return `${start} · ${typeof seconds==='number'&&Number.isFinite(seconds)?num(seconds/60,seconds%60?1:0)+ui(' 分钟严格窗口'):ui('窗口待核验')}`;
}
function nextOrdinaryClockNote(s){
  const p=s?.next_ordinary_execution_clock;
  const keys=['after_signal_date','previous_delay_minutes','previous_window_seconds','execution_delay_minutes','execution_window_seconds'];
  if(!p||typeof p!=='object'||Array.isArray(p)||Object.keys(p).length!==keys.length||
    !keys.every(key=>Object.prototype.hasOwnProperty.call(p,key))||
    !keys.slice(1).every(key=>Number.isInteger(p[key]))||
    p.execution_delay_minutes!==25||p.execution_window_seconds!==1500||
    p.previous_delay_minutes<0||p.previous_delay_minutes>180||p.previous_window_seconds<1||p.previous_window_seconds>3600||
    p.previous_delay_minutes===25&&p.previous_window_seconds===1500||
    s.execution_delay_minutes!==p.previous_delay_minutes||s.execution_window_seconds!==p.previous_window_seconds||
    typeof p.after_signal_date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(p.after_signal_date))return '';
  const day=new Date(p.after_signal_date+'T00:00:00Z');
  const signal=s.plan?.signal_date||s.plan?.source_date||s.plan_signal_date||s.signal_date;
  if(!Number.isFinite(day.getTime())||day.toISOString().slice(0,10)!==p.after_signal_date||signal!==p.after_signal_date)return '';
  return ui('下一新信号起 · 纽约09:55–10:20；当前信号保留原窗口');
}
function policy(s){
  const auto=automaticCompletionNote(s),ids=automaticPolicyIds(s),strict=activeBookRows(s).filter(b=>!ids.has(b.strategy_id));
  const scope=auto?ui('其余策略（')+strict.map(b=>strategyLabel(b.strategy_id,b)).join('、')+'）':ui('活动策略');
  const window=strict.length||!auto?`${scope} · ${paperCatchup(s)?ui('同日手动补执行 · 原计划 '):''}${strictWindow(s)} · ${s.allow_partial_quotes?ui('逐股检查，异常跳过留现金'):ui('组合报价全部合格后执行')}`:'';
  return ui`独立账户各 $10,000 · ${[auto,window,nextOrdinaryClockNote(s)].filter(Boolean).join('；')}`;
}
function decisionLabel(d){if(!d)return ui('已处理');if(d.qty_after<d.target_qty)return d.qty_after>d.qty_before?ui('部分成交 · 资金限制'):ui('跳过 · 资金不足');return d.reason==='FILLED'?ui('已成交'):d.reason==='TARGET_SATISFIED'?ui('持仓已符合'):ui('已处理');}
function reasonLabel(reason){const r=String(reason||'');return /cash|现金|资金/i.test(r)?ui('资金不足'):/spread|价差/i.test(r)?ui('价差超限'):/quote|age|timestamp|时间|行情|报价|30/i.test(r)?ui('行情不合格'):ui('检查未通过');}
function skipSummary(rows){return list(rows).map(row=>`${String(row.code||'').replace(/^US\./,'')}：${row.reason||ui('报价待核验')}`).join('；');}
function recordedClock(record){
  const valid=day=>typeof day==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(day)&&Number.isFinite(Date.parse(day+'T00:00:00Z'))&&new Date(day+'T00:00:00Z').toISOString().slice(0,10)===day;
  return record&&valid(record.signal_date)&&valid(record.execution_date)?{signal_date:record.signal_date,execution_date:record.execution_date}:null;
}
function planClock(b){
  if(!b.plan)return null;
  let execution=b.plan.execution_date||b.plan_metadata?.execution_date||b.execution_date;
  const opening=b.execution_time_utc||b.next_open_utc;
  if(!execution&&typeof opening==='string'&&/(?:Z|[+-]\d{2}:\d{2})$/.test(opening)&&Number.isFinite(Date.parse(opening)))execution=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(opening));
  return recordedClock({signal_date:b.plan.signal_date||b.plan.source_date||b.plan_metadata?.signal_date,execution_date:execution});
}
function matchesPlan(record,b){
  const clock=recordedClock(record),plan=planClock(b);
  return !!clock&&!!plan&&clock.signal_date===plan.signal_date&&clock.execution_date===plan.execution_date;
}
function bookCompletionPill(b,s){
  const value=b.status||s.status,plan=planClock(b),clock=recordedClock(b.execution),current=recordedClock(s);
  const rows=list(b.plan?.rows||b.plan?.targets),batchStatus=b.execution?.status;
  const recorded=!!clock&&rows.length>0&&rows.every(row=>row&&recordCode(row)&&typeof row.target_weight==='number'&&Number.isFinite(row.target_weight)&&row.target_weight>=0&&row.target_weight<=1)&&['EXECUTED','PARTIALLY_EXECUTED'].includes(batchStatus);
  const previous=recorded&&current&&clock.signal_date<current.signal_date&&clock.execution_date<current.execution_date;
  const previousText=batchStatus==='EXECUTED'?ui('上期计划已执行'):ui('上期部分执行');
  if(value==='TARGET_ONLY'){
    const dates=plan?ui`<br><small>信号 ${esc(plan.signal_date)} · 执行 ${esc(plan.execution_date)}</small>`:'';
    const history=previous?ui`<br><small>${previousText} · 信号 ${esc(clock.signal_date)} · 执行 ${esc(clock.execution_date)}</small>`:'';
    return `<span>${statusPill(value)}${dates}${history}</span>`;
  }
  if(!['EXECUTED','PARTIALLY_EXECUTED'].includes(value))return statusPill(value);
  const same=recorded&&batchStatus===value&&current&&matchesPlan(b.execution,b)&&clock.signal_date===current.signal_date&&clock.execution_date===current.execution_date;
  const verifiedPrevious=previous&&batchStatus===value;
  const text=same?label(value):verifiedPrevious?previousText:ui('执行批次待核验');
  const dates=clock?ui`<br><small>信号 ${esc(clock.signal_date)} · 执行 ${esc(clock.execution_date)}</small>`:'';
  return `<span>${statusPill(same||verifiedPrevious?value:'WAITING_SOURCE',text)}${dates}</span>`;
}
function executionCheckLabel(record,b){
  const clock=recordedClock(record);
  return clock?ui`${matchesPlan(record,b)?ui('本期行情检查未通过项'):ui('历史执行检查')} · 信号 ${clock.signal_date} · 执行 ${clock.execution_date}`:ui('执行检查记录 · 批次日期待核验');
}
function render(s){snapshot=s;const books=bookRows(s);renderMembership(s,books);$('status').textContent=s.halted?ui('已停止'):s.running?label(s.status)||ui('运行中'):ui('已暂停');$('signal-date').textContent=s.signal_date||s.source?.signal_date||'—';$('next-open').textContent=ny(s.execution_time_utc||s.next_expected_execution_utc||s.next_expected_open_utc||s.upcoming_open_utc||s.next_open_utc||s.source?.next_expected_open_utc||s.source?.next_open_utc);const executionAt=s.execution_time_utc||s.next_expected_execution_utc||s.next_expected_open_utc||s.upcoming_open_utc||s.next_open_utc||s.source?.next_expected_open_utc||s.source?.next_open_utc;const executionDate=new Date(executionAt||'');$('execution-jst').textContent=Number.isFinite(executionDate.getTime())?ui('日本 ')+new Intl.DateTimeFormat(locale,{timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(executionDate):'';$('quote-source').textContent=s.connection_error?ui('MOOMOO · 行情待核验'):`MOOMOO${s.quote_asof?' · '+ny(s.quote_asof):ui(' · 等待最新盘口')}`;$('reason').textContent=notes(s.reason==='WAITING_SOURCE'?ui('日更正在生成最新完整信号，账户等待计划执行时点。'):s.reason,s.status==='MISSED_OPEN'?s.last_error:'')||s.last_error||(paperCatchup(s)?ui('仅处理原批次尚未完成的目标；每笔成交保留实际时间。'):ui('按各活动账户自己的目标持仓，在计划执行时点检查买卖。'));const catchup=catchupNote(s);if(catchup)$('reason').textContent=catchup+' '+$('reason').textContent;$('asof').textContent=s.asof?ui('账本更新 ')+ny(s.asof):ui('独立资金与成交记录');renderControls();
  $('books').innerHTML=books.map(b=>{const ret=b.return_fraction??(typeof b.return_pct==='number'?b.return_pct/100:null);return `<tr><td class="strategy" style="color:${colors[b.strategy_id]||'#25312c'}">${esc(strategyLabel(b.strategy_id,b))}<small>${esc(b.account_id)}</small></td><td>${bookCompletionPill(b,s)}</td><td>${num(b.equity)}</td><td class="${ret>=0?'positive':'negative'}">${pct(ret)}</td><td>${pct(b.max_drawdown??b.max_drawdown_fraction)}</td><td>${num(b.cash)}</td><td>${list(b.positions).filter(p=>p.qty>0).length}</td><td>${num(b.fees??b.total_fees)}</td><td>${num(b.trade_count??b.fills_count??list(b.trades||b.orders).filter(t=>['FILLED','FILLED_ALL'].includes(t.status)).length,0)}</td></tr>`}).join('')||ui('<tr><td colspan="9" class="empty">活动账户尚未初始化</td></tr>');
  $('execution-policy').textContent=policy(s);
  const upcoming=s.next_expected_execution_utc,current=s.execution_time_utc;
  $('next-window').textContent=upcoming&&current&&new Date(upcoming).getTime()>new Date(current).getTime()?ui`下一窗口 ${ny(upcoming)} · 待完整信号`:'';
  $('positions').innerHTML=books.map(b=>{
    const positions=list(b.positions).filter(p=>p.qty>0),actions=list(b.planned_actions),targets=b.plan?.rows||b.plan?.targets||[];
    const execution=matchesPlan(b.execution,b)?b.execution:null;
    const skipped=new Map(list(execution?.skipped).map(row=>[row.code,row.reason]));
    const processed=new Set(execution?.processed_codes||execution?.executed_codes||[]),decisions=new Map(list(execution?.execution_decisions).map(row=>[row.code,row])),byCode=new Map();
    const previousSkips=execution?[]:list(b.execution?.skipped||b.skipped);
    const previousChecks=previousSkips.length?`<p class="note">${esc(executionCheckLabel(b.execution,b))}：${esc(skipSummary(previousSkips))}</p>`:'';
    for(const p of positions)byCode.set(p.code,{...p});
    for(const t of targets){const c=t.code||'US.'+t.ticker;byCode.set(c,{...(byCode.get(c)||{code:c,qty:0}),...t});}
    for(const a of actions)byCode.set(a.code,{...(byCode.get(a.code)||{qty:0}),...a});
    for(const [code] of skipped)if(!byCode.has(code))byCode.set(code,{code,qty:0});
    const rows=[...byCode.values()];
    return ui`<article class="panel book-panel"><div class="panel-head"><h2 style="color:${colors[b.strategy_id]||'#25312c'}">${esc(strategyLabel(b.strategy_id,b))}</h2>${bookCompletionPill(b,s)}</div><div class="table-wrap"><table><thead><tr><th>股票</th><th>现有股数</th><th>目标权重</th><th>动作 / 检查</th></tr></thead><tbody>${rows.map(p=>`<tr><td>${esc(String(p.code||p.ticker).replace(/^US\./,''))}</td><td>${num(p.current_qty??p.qty??0,0)}${p.mark_asof?ui`<small>估值至 ${esc(ny(p.mark_asof))}</small>`: ""}</td><td>${typeof p.target_weight==='number'?num(p.target_weight*100,2)+'%':'—'}</td><td title="${esc(skipped.get(p.code)||'')}">${esc(skipped.has(p.code)?(automaticCompletionNote(s,b.strategy_id)?ui('等待 · '):ui('跳过 · '))+reasonLabel(skipped.get(p.code)):processed.has(p.code)?decisionLabel(decisions.get(p.code)):p.side||p.action||ui('待执行计算'))}</td></tr>`).join('')||ui('<tr><td colspan="4" class="empty">当前空仓，等待下一完整信号</td></tr>')}</tbody></table></div><p class="subline">信号 ${esc(b.plan?.signal_date||b.plan?.source_date||s.signal_date||'—')} · 原目标现金 ${typeof b.plan?.target_cash_weight==='number'?num(b.plan.target_cash_weight*100,2)+'%':'—'}</p>${previousChecks}<p class="note">${esc(notes(b.reason||b.last_error||(paperCatchup(s)?ui('同日手动补执行，数量按实际检查时行情和本账户资金计算。'):ui('数量按计划执行时行情和本账户资金计算。')),b.status==='MISSED_OPEN'?b.connection_error:''))}</p></article>`;
  }).join('');
  renderChart(books);renderTrades();renderBroker(s.broker,s);
}
function tradeTimestamp(t){
  for(const value of [t.filled_at,t.created_at]){
    if(typeof value!=='string'||!value.trim())continue;
    const time=Date.parse(value);if(Number.isFinite(time))return time;
  }
  return null;
}
function renderTrades(){if(!snapshot)return;let trades=list(snapshot.trades);if(!trades.length)trades=bookRows(snapshot).flatMap(b=>list(b.trades||b.orders).map(t=>({strategy_id:b.strategy_id,...t})));const sid=$('trade-strategy').value,sym=$('trade-symbol').value.trim().toUpperCase();const shown=[...trades].filter(t=>(!sid||t.strategy_id===sid)&&(!sym||String(t.code).toUpperCase().includes(sym))).sort((a,b)=>{
    const left=tradeTimestamp(a),right=tradeTimestamp(b);
    if(left===null)return right===null?0:1;
    return right===null?-1:right-left;
  }).slice(0,100);$('trades').innerHTML=shown.map(t=>`<tr><td>${esc(ny(t.filled_at||t.created_at))}</td><td>${esc(strategyLabel(t.strategy_id,t))}</td><td>${esc(t.signal_date)}</td><td>${esc(String(t.code||'').replace(/^US\./,''))}</td><td>${esc(t.side)}</td><td>${num(t.filled_qty??t.dealt_qty??t.qty,0)}</td><td>${num(t.fill_price??t.dealt_avg_price,4)}</td><td>${num(t.fee,4)}</td><td>${statusPill(t.status)}</td></tr>`).join('')||(paperCatchup(snapshot)?ui('<tr><td colspan="9" class="empty">尚无匹配成交；同日手动补执行以实际成交记录为准。</td></tr>'):ui('<tr><td colspan="9" class="empty">尚无匹配成交；错过的开盘信号不会补记成交。</td></tr>'));}
function valuationNote(p){
  if(!p?.observed_at_utc)return ui`标价时间 ${ny(p?.asof)}`;
  const coverage=p.complete_live_coverage?ui('持仓报价全部通过本次检查'):ui`混合标价 · 本次合格 ${num(p.fresh_held_count,0)}/${num(p.held_count,0)}`;
  const failures=list(p.failed_quotes).map(q=>`${String(q.code).replace(/^US\./,'')}：${q.reason}`).join('；');
  return ui`观测 ${ny(p.observed_at_utc)} · 实际标价最早 ${ny(p.held_asof_min)} / 最晚 ${ny(p.held_asof_max)} · ${coverage}${failures?ui(' · 缺口 ')+failures:''}`;
}
function renderChart(books){
  const series=books.map(b=>({id:b.strategy_id,name:strategyLabel(b.strategy_id,b),points:list(b.nav_history).map(p=>({x:new Date(p.observed_at_utc||p.asof||p.time||p.date).getTime(),record:p,y:p.nav??(typeof p.equity==='number'?p.equity/(b.initial_cash||10000):NaN)})).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y))}));
  const pts=series.flatMap(s=>s.points),host=$('nav-chart');
  if(!pts.length){host.innerHTML=paperCatchup(snapshot)?ui('<span class="muted">起始净值 1.0000；等待实际成交与行情计价记录。</span>'):ui('<span class="muted">起始净值 1.0000；等待第一笔开盘成交与行情计价记录。</span>');return;}
  const xs=pts.map(p=>p.x),ys=pts.map(p=>p.y),lo=Math.min(...ys,1),hi=Math.max(...ys,1),x0=Math.min(...xs),x1=Math.max(...xs),span=Math.max(hi-lo,.002);
  const width=Math.max(320,host.clientWidth),left=54,right=width-18,top=18,bottom=207;
  const low=lo-span*.1,high=hi+span*.1,x=v=>left+(v-x0)/Math.max(x1-x0,1)*(right-left),y=v=>bottom-(v-low)/(high-low)*(bottom-top);
  let svg=ui`<svg viewBox="0 0 ${width} 250" role="img" aria-label="活动纸面账户的实际净值路径"><title>纸面账户净值 · 真实记录时间</title><desc>按实际持仓和可核验报价计价，各账户按自己的起点从净值1开始。不存在的日期和缺失估值没有补造。</desc>`;
  for(let i=0;i<4;i++){const value=low+(high-low)*i/3;svg+=`<line x1="${left}" x2="${right}" y1="${y(value)}" y2="${y(value)}" stroke="#e2e3dc"/><text x="${left-9}" y="${y(value)+4}" fill="#606770" font-size="11" text-anchor="end">${num(value,3)}</text>`;}
  svg+=`<line x1="${left}" x2="${right}" y1="${y(1)}" y2="${y(1)}" stroke="#939ba5" stroke-dasharray="3 5"/>`;
  for(const item of series)if(item.points.length){svg+=`<polyline fill="none" stroke="${colors[item.id]}" stroke-width="2.3" stroke-linejoin="round" points="${item.points.map(p=>x(p.x)+','+y(p.y)).join(' ')}"><title>${esc(item.name)}</title></polyline>`;const p=item.points.at(-1);svg+=`<circle cx="${x(p.x)}" cy="${y(p.y)}" r="3.5" fill="${colors[item.id]}"><title>${esc(item.name)} · ${num(p.y,4)} · ${esc(valuationNote(p.record))}</title></circle>`;}
  const ticks=x0===x1?[x0]:[x0,x0+(x1-x0)/2,x1];
  for(let i=0;i<ticks.length;i++){const stamp=ticks[i],anchor=i===0?'start':i===ticks.length-1?'end':'middle';svg+=`<text x="${x(stamp)}" y="232" fill="#606770" font-size="11" text-anchor="${anchor}">${esc(new Intl.DateTimeFormat(locale,{timeZone:'America/New_York',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(stamp)))}</text>`;}
  svg+='</svg>';host.innerHTML=svg+series.filter(s=>s.points.length).map(s=>`<p class="note">${esc(s.name)} · ${esc(valuationNote(s.points.at(-1).record))}</p>`).join('');
  host.innerHTML+=books.filter(b=>b.valuation&&b.valuation.nav_recorded===false).map(b=>ui`<p class="note">${esc(strategyLabel(b.strategy_id,b))} · 本次未更新净值 · ${esc(valuationNote(b.valuation))}${list(b.valuation.unmarked_codes).length?ui(' · 缺少真实标价 ')+esc(b.valuation.unmarked_codes.join('、')):''}</p>`).join('');
}
function brokerCatchup(b){
  const r=b.same_day_catchup,signal=b.plan?.signal_date||b.plan?.source_date;
  const aware=v=>typeof v==='string'&&/(?:Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v));
  if(!r||typeof r!=='object'||!signal||r.signal_date!==signal||!aware(b.execution_time_utc)||
    !aware(r.authorized_at_utc)||!aware(r.deadline_utc)||Date.parse(r.deadline_utc)<=Date.parse(r.authorized_at_utc))return null;
  const day=v=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(v));
  const execution=day(b.execution_time_utc);
  return r.execution_date===execution&&(!b.execution_date||b.execution_date===execution)&&
    day(r.authorized_at_utc)===execution&&day(r.deadline_utc)===execution?r:null;
}
function brokerCatchupNote(b,now=Date.now()){
  const r=brokerCatchup(b);if(!r)return '';
  const state=now>=Date.parse(r.deadline_utc)?ui('当日曾授权补执行，现已截止'):now<Date.parse(r.authorized_at_utc)?ui('补执行授权时点尚未到达'):ui('补执行授权窗口内');
  return ui`券商同日手动补执行 · 授权 ${ny(r.authorized_at_utc)} · 截止 ${ny(r.deadline_utc)}（纽约 / 美东时间） · ${state}；实际成交以券商确认时间和均价为准。`;
}
function brokerWindow(b,timeZone='America/New_York'){
  const start=new Date(b.ordinary_execution_time_utc||b.execution_time_utc||''),deadline=new Date(b.execution_deadline_utc||'');
  const ordinaryDeadline=new Date(b.ordinary_execution_deadline_utc||'');
  const seconds=b.execution_window_seconds,catchup=brokerCatchup(b),manual=brokerManualCompletion(b);
  const configured=Number.isFinite(start.getTime())&&typeof seconds==='number'&&Number.isFinite(seconds)?new Date(start.getTime()+seconds*1000):null;
  const end=Number.isFinite(ordinaryDeadline.getTime())?ordinaryDeadline:catchup||manual?configured:(Number.isFinite(deadline.getTime())?deadline:configured);
  const formatter=new Intl.DateTimeFormat(locale,{timeZone,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  const zone=timeZone==='Asia/Tokyo'?ui('日本'):ui('美东');
  return Number.isFinite(start.getTime())&&end&&Number.isFinite(end.getTime())?`${catchup?ui('原计划 · '):''}${zone} ${formatter.format(start)} → ${formatter.format(end)}`:ui('执行窗口待核验');
}
function cooldownText(retryAt,start,end,running,now=Date.now()){
  if(Number.isFinite(end)&&end>0&&now>=end)return ui('本期执行窗口已结束，不再自动重试');
  const remaining=Math.max(0,Math.ceil((retryAt-now)/1000));
  if(!running)return remaining?ui`冷却剩余 ${remaining} 秒 · 自动执行暂停`:ui('冷却结束 · 自动执行暂停');
  if(Number.isFinite(start)&&start>0&&now<start)return ui('等待执行窗口');
  return remaining?ui`冷却剩余 ${remaining} 秒`:ui('冷却结束 · 等待最新合格卖一价');
}
function cooldownMarkup(after,b){
  const retryAt=Date.parse(after),start=Date.parse(b.execution_time_utc),end=Date.parse(b.execution_deadline_utc);
  if(!Number.isFinite(retryAt))return '';
  const running=!!b.running&&b.status!=='HALTED';
  const startValue=Number.isFinite(start)?start:0,endValue=Number.isFinite(end)?end:0;
  return `<span class="broker-cooldown" data-retry-at="${retryAt}" data-window-start="${startValue}" data-window-end="${endValue}" data-running="${running?'1':'0'}">${esc(cooldownText(retryAt,startValue,endValue,running))}</span>`;
}
function updateCooldowns(){
  document.querySelectorAll('#broker-panel .broker-cooldown').forEach(node=>{
    node.textContent=cooldownText(Number(node.dataset.retryAt),Number(node.dataset.windowStart),Number(node.dataset.windowEnd),node.dataset.running==='1');
  });
}
function brokerOrderRow(t,maxReprices,b,latestBuy){
  const pending=['SUBMITTED','PENDING_RECONCILE','UNKNOWN','FILLED_PART'].includes(t.status);
  const market=t.order_type==='MARKET';
  const terminalBuy=t.side==='BUY'&&['FAILED','CANCELLED_ALL','CANCELLED_PART'].includes(t.status);
  const fillQty=t.dealt_qty??t.filled_qty??t.fill_qty;
  const fillPrice=t.dealt_avg_price??t.fill_price;
  const count=Number.isInteger(t.reprice_count)&&t.reprice_count>=0?t.reprice_count:null;
  const repriceCount=count===null?'—':`${count}${maxReprices!==null?' / '+maxReprices:''}`;
  const attempted=typeof t.last_reprice_limit==='number'&&Number.isFinite(t.last_reprice_limit);
  const attemptLabel=t.reprice_status==='ACKNOWLEDGED'?ui('已接收限价'):t.reprice_status==='NOT_SENT'?ui('未发送限价'):ui('待核对限价');
  const lastReprice=attempted?`${attemptLabel} $${num(t.last_reprice_limit,4)} · ${ny(t.last_reprice_at)}`:ui('尚未尝试改单');
  const repriceStatus=t.reprice_status&&t.reprice_status!=='NONE'?`<small>${esc(label(t.reprice_status))}</small>`:'';
  const retry=terminalBuy&&t.terminal_retry_after_utc?(latestBuy===t
    ?ui`<small>失败后重试 · ${cooldownMarkup(t.terminal_retry_after_utc,b)}</small>`
    :ui('<small>后续买单已另行记录</small>')):'';
  return `<tr><td>${esc(ny(t.filled_at||t.created_at))}</td><td>${esc(String(t.code||'').replace(/^US\./,''))}${t.order_id?ui`<small>券商委托号 ${esc(t.order_id)}</small>`:''}</td><td>${esc(t.side)}<small>${market?ui('市价单'):ui('限价单')}</small></td><td>${num(t.qty,0)}</td><td>${pending&&!(typeof fillQty==='number'&&fillQty>0)?ui('待券商确认'):num(fillQty,0)}</td><td>${pending&&!(typeof fillPrice==='number'&&fillPrice>0)?ui('待券商确认'):num(fillPrice,4)}</td><td>${market?ui('—<small>市价单不改价；以实际成交均价为准</small>'):`${esc(repriceCount)}<small>${esc(lastReprice)}</small>${repriceStatus}`}</td><td>${statusPill(t.status)}${retry}</td></tr>`;
}
function brokerSkippedRows(b){
  const groups=new Map();
  for(const row of list(b.skipped)){
    const origin=row.signal_date!==undefined||row.execution_date!==undefined?row:b.skipped_source||b.execution;
    const heading=executionCheckLabel(origin,b),current=matchesPlan(origin,b);
    const retry=row.retry_after_utc?(current?` · ${cooldownMarkup(row.retry_after_utc,b)}`:ui` · 记录重试时点 ${esc(ny(row.retry_after_utc))}`):'';
    const content=`<div><strong>${esc(String(row.code||'').replace(/^US\./,''))}</strong> · ${esc(row.reason||ui('执行检查未通过'))}${retry}</div>`;
    groups.set(heading,(groups.get(heading)||'')+content);
  }
  return [...groups].map(([heading,rows])=>`<div class="broker-skips"><strong>${esc(heading)}</strong>${rows}</div>`).join('')+(groups.size?ui('<p class="note">此处显示原行情检查记录；完整计划与已返回的持仓范围见上方目标、退出及其他持仓表。</p>'):'');
}
function brokerManualCompletion(b){
  const r=b.published_target_manual_completion;
  const aware=v=>typeof v==='string'&&/(?:Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v));
  // Both owner paths publish this field; source READY/TARGET_ONLY is not execution status.
  return ['OWNER_PUBLISHED_TARGET_MANUAL_COMPLETION_R1','OWNER_NATIVE_CURRENT_MANUAL_COMPLETION_R1'].includes(r?.schema)&&
    r.strategy_id===b.strategy_id&&['ACTIVE','EXPIRED','COMPLETED'].includes(r.status)&&
    typeof r.manual_id==='string'&&r.manual_id&&matchesPlan(r,b)&&
    (!b.execution_date||r.execution_date===b.execution_date)&&
    aware(r.authorized_at_utc)&&aware(r.deadline_utc)&&Date.parse(r.deadline_utc)>Date.parse(r.authorized_at_utc)?r:null;
}
function brokerPreviousManualCompletion(b,s){
  const a=b.published_target_alignment,raw=b.published_target_manual_completion;
  const prior=recordedClock(raw),current=recordedClock(s);
  const hash=v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
  const id=v=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(v);
  const aware=v=>typeof v==='string'&&/(?:Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v));
  if(a?.schema!=='PUBLISHED_TARGET_ALIGNMENT_R1'||raw?.status!=='COMPLETED'||!prior||!current||
    prior.signal_date>=current.signal_date||prior.execution_date>=current.execution_date||prior.signal_date>=prior.execution_date||
    a.strategy_id!==b.strategy_id||a.signal_date!==prior.signal_date||a.execution_date!==prior.execution_date||
    !id(raw.manual_id)||!id(raw.alignment_id)||a.request?.alignment_id!==raw.alignment_id||
    a.request.expected_strategy_id!==b.strategy_id||a.request.signal_date!==prior.signal_date||
    !hash(raw.published_target_sha256)||a.published_target_sha256!==raw.published_target_sha256||
    a.request.expected_target_sha256!==raw.published_target_sha256||!hash(raw.receipt_sha256)||!aware(raw.session_close_utc))return null;
  // Reuse the manual-record guard against its original owner alignment only;
  // this historical binding is never passed to current completion or controls.
  const r=brokerManualCompletion({...b,plan:a,execution_date:a.execution_date});
  if(!r)return null;
  const authorized=Date.parse(r.authorized_at_utc),deadline=Date.parse(r.deadline_utc),close=Date.parse(r.session_close_utc);
  const day=v=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(v));
  return deadline-authorized<=600000&&deadline<=close&&[authorized,deadline,close].every(v=>day(v)===prior.execution_date)?r:null;
}
function brokerManualCompletionNote(b,s){
  const r=brokerManualCompletion(b),raw=b.published_target_manual_completion;
  if(!r){
    const previous=brokerPreviousManualCompletion(b,s);
    if(previous){
      const day=v=>v.slice(5).replace('-','/');
      const current=!planClock(b)?ui('当前下期目标待发布'):ui('本记录不代表本期执行状态');
      return ui`<p id="broker-manual-completion" class="binding-note"><strong>上期补单已完成（信号${esc(day(previous.signal_date))}→执行${esc(day(previous.execution_date))}）</strong> · ${esc(current)}；历史补单记录 ${esc(previous.manual_id)}，旧窗口不授予本期补单权限。</p>`;
    }
    return raw&&typeof raw==='object'&&Object.keys(raw).length
      ?ui('<p id="broker-manual-completion" class="binding-note">本次手动补单 · 待核验；当前记录缺少可确认的授权窗口或身份。</p>'):'';
  }
  const state={ACTIVE:ui('授权有效'),EXPIRED:ui('已截止'),COMPLETED:ui('本次补单已执行')}[r.status];
  const formatter=timeZone=>new Intl.DateTimeFormat(locale,{timeZone,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  const window=timeZone=>{const f=formatter(timeZone);return `${f.format(new Date(r.authorized_at_utc))} → ${f.format(new Date(r.deadline_utc))}`;};
  return ui`<p id="broker-manual-completion" class="binding-note"><strong>本次手动补单 · ${esc(state)}</strong> · 美东 ${esc(window('America/New_York'))}<br>日本 ${esc(window('Asia/Tokyo'))} · 补单记录 ${esc(r.manual_id)}；实际成交以券商对账为准。</p>`;
}
function brokerPlanCompleted(b){
  const c=b.published_target_conversion;
  const converted=c?.schema==='OWNER_PUBLISHED_TARGET_CONVERSION_R1'&&c.strategy_id===b.strategy_id&&
    c.status==='COMPLETED'&&matchesPlan({signal_date:c.last_signal_date,execution_date:c.last_execution_date},b);
  return !!planClock(b)&&(b.status==='EXECUTED'||converted||brokerManualCompletion(b)?.status==='COMPLETED');
}
function brokerPlanSummary(b,orders,pendingCount){
  const clock=planClock(b),knownOrders=Array.isArray(b.orders||b.trades)&&orders.every(order=>
    ['FILLED_ALL','FAILED','CANCELLED_ALL','CANCELLED_PART','CANCELLED_BEFORE_SEND',
     'SUBMITTED','PENDING_RECONCILE','UNKNOWN','FILLED_PART'].includes(order.status));
  const completed=brokerPlanCompleted(b);
  const progress=pendingCount>0||['PENDING_RECONCILE','UNKNOWN'].includes(b.status)?ui('等待券商对账')
    :completed?ui('本期计划已完成'):!clock?ui('计划状态待核验')
    :b.status==='PARTIALLY_EXECUTED'?ui('本期部分执行'):ui('计划待处理');
  return ui`<div id="broker-plan-summary" class="broker-plan-summary" role="status"><div><span>信号日</span><strong>${esc(clock?.signal_date||b.plan?.signal_date||b.plan?.source_date||ui('待核验'))}</strong></div><div><span>计划进度</span><strong class="${completed&&pendingCount===0?'plan-complete':''}">${esc(progress)}</strong></div><div><span>未完成委托</span><strong>${knownOrders?num(pendingCount,0):'—'} <small>笔</small></strong><small>仅统计最近返回的委托</small></div></div>`;
}
function brokerCashNote(b){
  if(brokerPlanCompleted(b))return ui('整数股与资金规则产生的余款保留在账户');
  const pendingBuy=list(b.orders||b.trades).some(order=>{
    const filled=order.dealt_qty??order.filled_qty??order.fill_qty;
    return order.side==='BUY'&&(!order.strategy_id||order.strategy_id===b.strategy_id)&&matchesPlan(order,b)&&
      ['SUBMITTED','PENDING_RECONCILE','FILLED_PART'].includes(order.status)&&
      typeof order.qty==='number'&&Number.isFinite(order.qty)&&typeof filled==='number'&&Number.isFinite(filled)&&filled>=0&&filled<order.qty;
  });
  return pendingBuy?ui('未完成买入的资金仍留在账户'):ui('剩余现金保留在账户');
}
function brokerConversionNote(b){
  const conversion=b.published_target_conversion;
  const known=conversion?.schema==='OWNER_PUBLISHED_TARGET_CONVERSION_R1'&&conversion.strategy_id===b.strategy_id;
  const text=known&&conversion.status==='ACTIVE'
    ?ui('持仓转换 · 尚未完成；后续合格信号在正常执行窗口按当期已冻结目标继续差额调仓。')
    :known&&conversion.status==='COMPLETED'
      ?ui('持仓转换 · 已完成；此后恢复当前所选策略的常规调仓。')
      :ui('持仓转换 · 待核验；尚无有效的账户转换状态记录。');
  return `<p id="broker-conversion" class="binding-note">${esc(text)}</p>`;
}
function renderBroker(b,s){
  let panel=$('broker-panel');
  if(!b){if(panel)panel.hidden=true;return;}
  if(!panel){panel=document.createElement('section');panel.id='broker-panel';panel.className='panel broker-panel';$('paper-overview').before(panel);}
  panel.hidden=false;
  const detailsState=new Map(Array.from(panel.querySelectorAll?.('details[id]')||[],node=>[node.id,node.open]));
  const tableScroll=new Map(Array.from(panel.querySelectorAll?.('.table-wrap[id]')||[],node=>[node.id,{top:node.scrollTop,left:node.scrollLeft}]));
  const account=b.account||{},orders=list(b.orders||b.trades),positions=list(b.positions||account.positions).filter(p=>p.qty>0);
  const targets=list(b.plan?.rows||b.plan?.targets).filter(p=>typeof p.target_weight==='number'&&p.target_weight>0);
  const targetCash=b.plan?.target_cash_weight,cash=b.cash??b.strategy_cash,equity=b.equity??b.strategy_equity;
  const planRows=positionTargetRows({...b,equity}),positive=planRows.filter(row=>row.target_weight>0);
  const exits=planRows.filter(row=>row.target_weight===0&&(row.action||row.side)==='SELL');
  const other=planRows.filter(row=>!positive.includes(row)&&!exits.includes(row));
  const heldKnown=accountSnapshotKnown(b),targetRows=b.plan?.rows||b.plan?.targets;
  const planKnown=Array.isArray(targetRows)||(targetRows!==null&&typeof targetRows==='object');
  const positiveCodes=new Set(positive.map(row=>row.code));
  const heldInTarget=positions.filter(row=>positiveCodes.has(recordCode(row))).length;
  const heldOutsideTarget=positions.filter(row=>!positiveCodes.has(recordCode(row))).length;
  const confirmed=orders.filter(t=>['FILLED_ALL','FILLED_PART'].includes(t.status)).length;
  const pendingCount=orders.filter(t=>['SUBMITTED','PENDING_RECONCILE','UNKNOWN','FILLED_PART'].includes(t.status)).length;
  const actualCash=typeof cash==='number'&&typeof equity==='number'&&equity>0?cash/equity:null;
  const reprice=b.reprice_policy||{},maxReprices=Number.isInteger(reprice.max_attempts_per_order)?reprice.max_attempts_per_order:null;
  const marketBuys=b.buy_order_type==='MARKET';
  const buyPolicy=marketBuys?ui('新买卖单采用市价单；先检查真实盘口、策略现金、可卖库存和股数，券商成交价与成交数量以对账为准。'):ui('新买单采用限价单。');
  const amendPolicy=reprice.enabled===true&&reprice.mode==='SAME_BROKER_ORDER_ID'&&typeof reprice.interval_seconds==='number'&&maxReprices!==null
    ?ui`历史未成交限价单先对账；间隔 ${num(reprice.interval_seconds,0)} 秒沿用原券商委托号改单，单笔最多 ${num(maxReprices,0)} 次。市价单不改价。`
    :ui('改单规则待核验。');
  const terminalPolicy=reprice.enabled===true&&typeof reprice.terminal_retry_cooldown_seconds==='number'&&Number.isInteger(reprice.max_terminal_retries_per_code)
    ?ui`买单确认失败后冷却 ${num(reprice.terminal_retry_cooldown_seconds,0)} 秒，再核验最新报价及剩余量，以新客户端标识${marketBuys?ui('提交市价单'):ui('提交限价单')}；单只最多 ${num(reprice.max_terminal_retries_per_code,0)} 次。`
    :ui('失败后重试规则待核验。');
  const runNote=b.status==='HALTED'?ui('自动执行已停止；当前不会改单或失败后重试，也不会补下旧信号。'):b.running?ui('两种处理都只在有效执行窗口内进行；待对账不视作成交。'):ui('自动执行暂停；当前不会改单或失败后重试。');
  const pending=orders.some(t=>['SUBMITTED','PENDING_RECONCILE','UNKNOWN','FILLED_PART'].includes(t.status));
  const latestBuy=new Map();
  for(const order of orders)if(order.side==='BUY'){
    const prior=latestBuy.get(order.code),created=Date.parse(order.created_at),priorCreated=Date.parse(prior?.created_at);
    if(!prior||!Number.isFinite(priorCreated)||Number.isFinite(created)&&created>=priorCreated)latestBuy.set(order.code,order);
  }
  panel.style?.setProperty('--strategy-color',colors[b.strategy_id]||'var(--accent)');
  const runState=b.status==='HALTED'?'HALTED':b.running===true?'RUNNING':b.running===false?'STOPPED':b.status;
  const riskState=b.status!==runState&&['ERROR','BLOCKED','PENDING_RECONCILE','UNKNOWN'].includes(b.status)?statusPill(b.status):'';
  const regularWindow=brokerWindow(b),windowKnown=regularWindow!==ui('执行窗口待核验'),nextClock=nextOrdinaryClockNote(b);
  const ruleKnown=typeof b.execution_window_seconds==='number'&&Number.isFinite(b.execution_window_seconds)&&
    (windowKnown||typeof b.execution_delay_minutes==='number'&&Number.isFinite(b.execution_delay_minutes));
  const executionRule=b.automatic_completion_policy?.enabled===true?b.automatic_completion_policy.schema_version===2?ui('仅常规窗口内自动续查，10:20后需单次手动授权'):ui('本账户已授权自动接续'):ruleKnown?strictWindow(b):'';
  const rawReason=[b.reason,b.last_error&&b.last_error!==b.reason?b.last_error:''].filter(Boolean).join(' · ');
  const manual=brokerManualCompletion(b);
  panel.innerHTML=ui`<div class="panel-head broker-heading"><div><span class="eyebrow">BROKER · SIMULATE</span><h2>MOOMOO 模拟账户 · ${esc(strategyLabel(b.strategy_id,b)||ui('策略待核验'))}</h2><p class="account-identity">${esc(b.account_id||ui('账户待核验'))}${heldKnown?ui` · 策略预算 <strong>$${num(b.budget||10000,0)}</strong> · ${ui('预算，不代表实际现金')}`:''}</p></div><div class="broker-status">${statusPill(runState)}${riskState}</div></div>
    ${!heldKnown?ui`<div class="account-unknown" role="status"><strong>当前账户资金与持仓尚未核验</strong><div class="broker-summary-facts"><p><span>策略预算</span><strong>$${num(b.budget||10000,0)}</strong><small>预算，不代表实际现金</small></p><p><span>历史委托 / 已确认成交</span><strong class="broker-history-count">${num(orders.length,0)} / ${num(confirmed,0)}</strong><small>历史记录不代表当前持仓 · 待确认 ${pendingCount} 笔</small></p></div></div>`:''}
    ${brokerPlanSummary(b,orders,pendingCount)}
    <p class="note broker-boundary">模拟账户 · 实盘执行已锁定</p>
    ${manual?.status==='EXPIRED'?ui('<p class="broker-permission">补单授权已截止；旧窗口不授予本期补单权限。</p>'):''}
    ${manual?.status==='ACTIVE'?ui`<p class="broker-permission">本次手动补单 · 授权有效 · 截止 美东 ${esc(ny(manual.deadline_utc))}</p>`:''}
    ${heldKnown?ui`<div class="broker-compare" aria-label="券商模拟目标与实际">${metric(ui('目标股票 / 已持有'),`${planKnown?positive.length:'—'} <span class="metric-divider">/</span> ${heldKnown?positions.length:'—'}`,ui`目标内持有 ${planKnown&&heldKnown?heldInTarget:'—'} 只 · 目标外剩余 ${planKnown&&heldKnown?heldOutsideTarget:'—'} 只<br>目标内未持有 ${planKnown&&heldKnown?positive.length-heldInTarget:'—'} 只 · 显式退出目标 <a href="#broker-exit-targets">${planKnown?exits.length:'—'} 只</a>；${planKnown&&heldKnown?exits.filter(row=>row.current_qty>0).length:'—'} 只仍有持仓`)}${metric(ui('目标现金 / 实际现金'),`${typeof targetCash==='number'?num(targetCash*100,2)+'%':'—'} <span class="metric-divider">/</span> ${typeof actualCash==='number'?num(actualCash*100,2)+'%':'—'}`,esc(brokerCashNote(b)))}${metric(ui('策略模拟持仓市值'),`$${typeof equity==='number'&&typeof cash==='number'?num(Math.max(0,equity-cash)):'—'}`,ui`策略现金 $${num(cash)} · 策略净值 $${num(equity)}`)}${metric(ui('最近委托 / 其中已成交'),`${num(orders.length,0)} <span class="metric-divider">/</span> ${num(confirmed,0)}`,ui`本页最近 ${orders.length} 笔 · 待确认 ${pendingCount} 笔`)}</div>`:''}
    ${heldKnown&&planKnown?ui('<p class="note broker-sizing-note">权重目标与实际持仓是不同口径。执行股数按当时资金、盘口和现金缓冲换算并取整，部分正权重目标可能不足一股；未持有项保留原目标，是否仍需下单以执行记录和券商对账为准。</p>'):''}
    ${pending?ui('<p class="broker-pending">券商委托仍需对账；只计入已确认的成交数量，待确认部分不记为成交。</p>'):''}
    ${planKnown?ui`<details id="broker-positive-targets" class="targets-details"${view==='presentation'?'':' open'}><summary>目标持仓 <span>${planKnown?positive.length+ui(' 只'):ui('待核验')} · 目标、现仓与权重差</span></summary>${brokerTargetTable(positive,'broker-positive-table')}<p class="note">现仓权重按券商返回的持仓市值计算，未记录市值的权重及差值保持未知；权重差 = 目标权重 − 现仓权重。实际执行股数由执行时的账户资金与合格盘口确定。</p></details>
    <details id="broker-exit-targets" class="targets-details"><summary>退出目标 <span>${planKnown?exits.length+ui(' 只'):ui('待核验')} · 原目标记录 SELL / 0%</span></summary>${brokerTargetTable(exits,'broker-exit-table')}</details>`:ui('<p class="note broker-target-unverified" role="status">目标计划尚未核验</p>')}
    ${other.length?ui`<details id="broker-other-targets" class="targets-details"><summary>其他持仓或目标 <span>${other.length} 只 · 未记录的目标保持未知</span></summary>${brokerTargetTable(other,'broker-other-table')}</details>`:''}
    <details id="broker-rules" class="rules-details broker-rules"><summary>执行与委托规则</summary>${b.status&&b.status!==runState?`<p class="binding-note">${statusPill(b.status)}</p>`:''}
      ${b.native_reset_epoch?.schema==='NATIVE_SIM_RESET_ADOPTION_R1'&&b.native_reset_epoch.target_strategy_id===b.strategy_id?ui`<p class="binding-note">重置后的模拟账户已接入 ${esc(strategyLabel(b.strategy_id,b))}；按新账户的资金和持仓计算目标，旧订单与成交保留在历史记录。</p>`:b.strategy_binding?ui`<p class="binding-note">原模拟账户已绑定 ${esc(strategyLabel(b.strategy_id,b))}；既有持仓按新目标做差额调整，历史委托与成交保留。</p>`:''}
      ${brokerConversionNote(b)}
      <div class="broker-session"><div><span>完整信号日</span><strong>${esc(b.plan?.signal_date||b.plan?.source_date||ui('待核验'))}</strong></div><div><span>常规开盘窗口 · 纽约</span><strong>${esc(regularWindow)}</strong>${windowKnown?`<small>${esc(brokerWindow(b,'Asia/Tokyo'))}</small>`:''}${nextClock?`<small class="next-ordinary-clock">${esc(nextClock)}</small>`:''}</div>${executionRule?ui`<div><span>常规执行规则</span><strong>${esc(executionRule)}</strong></div>`:''}</div>
      ${brokerManualCompletionNote(b,s)}
      ${rawReason?ui`<p class="status-note broker-reason"><strong>原始状态说明</strong><span class="owner-reason">${esc(rawReason)}</span></p>`:''}
      ${b.reason==='CONSENSUS_RESOURCE_FLOOR'?`<p class="note">${esc(notes(b.reason))}</p>`:''}
      <p class="broker-window">券商模拟独立执行规则 · ${esc(strategyLabel(b.strategy_id,b))}</p>${brokerCatchupNote(b)?`<p class="status-note">${esc(brokerCatchupNote(b))}</p>`:''}<p class="broker-policy"><span class="policy-label">新买单</span> ${esc(buyPolicy)}<br><span class="policy-label">有效委托</span> ${esc(amendPolicy)}<br><span class="policy-label">确认失败</span> ${esc(terminalPolicy)}<br><strong>${esc(runNote)}</strong></p><p class="note">MOOMOO 账户总余额由券商预设；本策略独立核算原模拟本金、持仓与成交。</p>${brokerSkippedRows(b)}</details>
    <details id="broker-orders" class="orders-details"><summary>${heldKnown?ui('最近券商委托与成交记录'):ui('历史委托与成交记录')} <span>显示最近 ${num(orders.length,0)} 笔 · ${pendingCount} 笔待确认</span></summary><p class="note">本页按接口返回范围显示最近 ${orders.length} 笔委托；原账户完整历史保留在账本中。</p><div id="broker-orders-table" class="table-wrap orders-table"><table><thead><tr><th>记录时间 · 纽约</th><th>股票 / 委托号</th><th>动作</th><th>委托股数</th><th>确认成交股数</th><th>确认成交均价</th><th>改单尝试次数 / 最近报价</th><th>券商状态</th></tr></thead><tbody>${orders.map(t=>brokerOrderRow(t,maxReprices,b,latestBuy.get(t.code))).join('')||ui('<tr><td colspan="8" class="empty">尚未向券商发送委托</td></tr>')}</tbody></table></div></details>`;
  for(const node of panel.querySelectorAll?.('details[id]')||[])if(detailsState.has(node.id))node.open=detailsState.get(node.id);
  for(const node of panel.querySelectorAll?.('.table-wrap[id]')||[]){const point=tableScroll.get(node.id);if(point){node.scrollTop=point.top;node.scrollLeft=point.left;}}
}
function refresh(force=false){
  if(force===true){refreshGeneration++;refreshQueued=true;}
  if(refreshFlight)return refreshFlight;
  if(pollTimer!==null){clearTimeout(pollTimer);pollTimer=null;}
  refreshLoading=true;renderReadFreshness();
  refreshFlight=(async()=>{
    do{
      refreshQueued=false;const generation=refreshGeneration;
      try{
        const value=await api('/api/applied/view');
        if(generation!==refreshGeneration)continue;
        render(value);
        const captured=Date.parse(value.display_snapshot?.captured_at_utc||'');
        lastSuccessAt=Number.isFinite(captured)?captured:Date.now();
        lastReadFailed=value.display_snapshot?.status==='STALE';error('');
      }catch(e){
        if(generation!==refreshGeneration)continue;
        lastReadFailed=true;
        error(e.message||ui('账户状态暂时无法核验；保留上次成功读取的数据。'));
      }
      renderReadFreshness();
    }while(refreshQueued);
  })().finally(()=>{
    refreshFlight=null;refreshLoading=false;renderReadFreshness();
    pollTimer=setTimeout(refresh,REFRESH_INTERVAL_MS);
  });
  return refreshFlight;
}
async function refreshBroker(){if(busy)return;activeOperations++;busy=true;renderControls();$('refresh').disabled=true;try{await refresh(true);}finally{busy=--activeOperations>0;$('refresh').disabled=false;if(snapshot)render(snapshot);}}
async function action(name){if(name!=='halt'&&busy||name==='start'&&$('start').disabled)return;activeOperations++;busy=true;renderControls();try{await api('/api/applied/'+name,{});await refresh(true);}catch(e){error(e.message);}finally{busy=--activeOperations>0;if(snapshot)render(snapshot);}}
initializeLanguage();
$('refresh').addEventListener('click',refreshBroker);for(const name of ['start','stop','halt'])$(name).addEventListener('click',()=>action(name));$('trade-strategy').addEventListener('change',renderTrades);$('trade-symbol').addEventListener('input',renderTrades);refresh();setInterval(()=>{updateCooldowns();renderReadFreshness();},1000);

'use strict';
const names={RAW_A2:'Raw A2',HGB_DIAG_5:'HGB＋对角风险',HGB_FACTOR_5:'HGB＋因子／收缩风险'};
const colors={RAW_A2:'#2357d9',HGB_DIAG_5:'#d97706',HGB_FACTOR_5:'#087f71'};
const states={WAITING_SOURCE:'等待完整数据',REFRESHING:'更新收盘数据',WAITING_CLOSE:'等待收盘信号',WAITING_OPEN:'等待计划执行',MISSED_OPEN:'本期执行未成交',WAITING_QUOTES:'等待合格报价',PARTIALLY_EXECUTED:'本期部分执行',CANCELLED_BEFORE_SEND:'未发送 · 检查未通过',READY:'已就绪',RUNNING:'运行中',STOPPED:'已暂停',HALTED:'已停止',BLOCKED:'执行检查未通过',ERROR:'异常待检查',EXECUTED:'本期计划已执行',FILLED:'纸面成交',FILLED_ALL:'券商模拟已成交',FILLED_PART:'部分成交',SUBMITTED:'券商已接收',PENDING_RECONCILE:'等待券商对账',UNKNOWN:'状态待确认',ATTEMPTING:'改单待券商核对',NOT_SENT:'改单未发送',ACKNOWLEDGED:'券商已接收改单'};
Object.assign(states,{FAILED:'券商确认失败',CANCELLED_ALL:'已全部撤销',CANCELLED_PART:'已部分撤销',RETRY_COOLDOWN:'失败后冷却中'});
const notes=(reason,last)=>[reason,last&&last!==reason?'上次检查：'+last:''].filter(Boolean).join(' · ');
let snapshot=null,token=null,busy=false;
const $=id=>document.getElementById(id);
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,d=2)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const pct=v=>typeof v==='number'&&Number.isFinite(v)?`${v>=0?'+':''}${num(v*100,2)}%`:'—';
const ny=v=>{if(!v)return '—';const date=new Date(v);return Number.isFinite(date.getTime())?new Intl.DateTimeFormat('zh-CN',{timeZone:'America/New_York',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(date):String(v)};
const label=v=>states[v]||v||'—';
const list=v=>Array.isArray(v)?v:(v&&typeof v==='object'?Object.entries(v).map(([k,item])=>typeof item==='object'?{code:k,...item}:{code:k,qty:item}):[]);
async function api(path,body){const opt={cache:'no-store'};if(body!==undefined){if(!token)token=(await api('/api/token')).token;Object.assign(opt,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(body)});}const r=await fetch(path,opt),j=await r.json();if(!r.ok||!j.ok)throw new Error(j.error||`HTTP ${r.status}`);return j.data;}
function error(message){$('error').hidden=!message;$('error').textContent=message||'';}
function bookRows(s){return Array.isArray(s.books)?s.books:Object.values(s.books||{});}
function policy(s){const seconds=s.execution_window_seconds,date=new Date(s.execution_time_utc||s.next_expected_execution_utc||'');const start=Number.isFinite(date.getTime())?'美东 '+new Intl.DateTimeFormat('zh-CN',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hour12:false}).format(date)+' 开始':'开盘后 '+num(s.execution_delay_minutes,0)+' 分钟开始';return `独立账户各 $10,000 · ${start} · ${typeof seconds==='number'?num(seconds/60,seconds%60?1:0)+' 分钟窗口':'窗口待核验'} · ${s.allow_partial_quotes?'逐股检查，异常跳过留现金':'组合报价全部合格后执行'}`;}
function decisionLabel(d){if(!d)return '已处理';if(d.qty_after<d.target_qty)return d.qty_after>d.qty_before?'部分成交 · 资金限制':'跳过 · 资金不足';return d.reason==='FILLED'?'已成交':d.reason==='TARGET_SATISFIED'?'持仓已符合':'已处理';}
function reasonLabel(reason){const r=String(reason||'');return /cash|现金|资金/i.test(r)?'资金不足':/spread|价差/i.test(r)?'价差超限':/quote|age|timestamp|时间|行情|报价|30/i.test(r)?'行情不合格':'检查未通过';}
function skipSummary(rows){return list(rows).map(row=>`${String(row.code||'').replace(/^US\./,'')}：${row.reason||'报价待核验'}`).join('；');}
function render(s){snapshot=s;const books=bookRows(s);$('status').textContent=s.halted?'已停止':s.running?label(s.status)||'运行中':'已暂停';$('signal-date').textContent=s.signal_date||s.source?.signal_date||'—';$('next-open').textContent=ny(s.execution_time_utc||s.next_expected_execution_utc||s.next_expected_open_utc||s.upcoming_open_utc||s.next_open_utc||s.source?.next_expected_open_utc||s.source?.next_open_utc);const executionAt=s.execution_time_utc||s.next_expected_execution_utc||s.next_expected_open_utc||s.upcoming_open_utc||s.next_open_utc||s.source?.next_expected_open_utc||s.source?.next_open_utc;const executionDate=new Date(executionAt||'');$('execution-jst').textContent=Number.isFinite(executionDate.getTime())?'日本 '+new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(executionDate):'';$('quote-source').textContent=s.connection_error?'MOOMOO · 行情待核验':`MOOMOO${s.quote_asof?' · '+ny(s.quote_asof):' · 等待最新盘口'}`;$('reason').textContent=notes(s.reason==='WAITING_SOURCE'?'日更正在生成最新完整信号，账户等待计划执行时点。':s.reason,s.status==='MISSED_OPEN'?s.last_error:'')||s.last_error||'按三个账户各自的目标持仓，在计划执行时点检查买卖。';$('asof').textContent=s.asof?'账本更新 '+ny(s.asof):'独立资金与成交记录';$('start').disabled=busy||!!s.running||!!s.halted;$('stop').disabled=busy||!s.running;$('halt').disabled=busy||!!s.halted;
  $('books').innerHTML=books.map(b=>{const ret=b.return_fraction??(typeof b.return_pct==='number'?b.return_pct/100:null);return `<tr><td class="strategy" style="color:${colors[b.strategy_id]||'#25312c'}">${esc(b.name||names[b.strategy_id]||b.strategy_id)}<small>${esc(b.account_id)}</small></td><td><span class="pill">${esc(label(b.status||s.status))}</span></td><td>${num(b.equity)}</td><td class="${ret>=0?'positive':'negative'}">${pct(ret)}</td><td>${pct(b.max_drawdown??b.max_drawdown_fraction)}</td><td>${num(b.cash)}</td><td>${list(b.positions).filter(p=>p.qty>0).length}</td><td>${num(b.fees??b.total_fees)}</td><td>${num(b.trade_count??b.fills_count??list(b.trades||b.orders).filter(t=>['FILLED','FILLED_ALL'].includes(t.status)).length,0)}</td></tr>`}).join('')||'<tr><td colspan="9" class="empty">三个账户尚未初始化</td></tr>';
  $('execution-policy').textContent=policy(s);
  const upcoming=s.next_expected_execution_utc,current=s.execution_time_utc;
  $('next-window').textContent=upcoming&&current&&new Date(upcoming).getTime()>new Date(current).getTime()?`下一窗口 ${ny(upcoming)} · 待完整信号`:'';
  $('positions').innerHTML=books.map(b=>{
    const positions=list(b.positions).filter(p=>p.qty>0),actions=list(b.planned_actions),targets=b.plan?.rows||b.plan?.targets||[];
    const skipped=new Map(list(b.execution?.skipped||b.skipped).map(row=>[row.code,row.reason]));
    const processed=new Set(b.execution?.processed_codes||[]),decisions=new Map(list(b.execution?.execution_decisions).map(row=>[row.code,row])),byCode=new Map();
    for(const p of positions)byCode.set(p.code,{...p});
    for(const t of targets){const c=t.code||'US.'+t.ticker;byCode.set(c,{...(byCode.get(c)||{code:c,qty:0}),...t});}
    for(const a of actions)byCode.set(a.code,{...(byCode.get(a.code)||{qty:0}),...a});
    for(const [code] of skipped)if(!byCode.has(code))byCode.set(code,{code,qty:0});
    const rows=[...byCode.values()];
    return `<article class="panel book-panel"><div class="panel-head"><h2 style="color:${colors[b.strategy_id]||'#25312c'}">${esc(b.name||names[b.strategy_id])}</h2><span class="pill">${esc(label(b.status||s.status))}</span></div><div class="table-wrap"><table><thead><tr><th>股票</th><th>现有股数</th><th>目标权重</th><th>动作 / 检查</th></tr></thead><tbody>${rows.map(p=>`<tr><td>${esc(String(p.code||p.ticker).replace(/^US\./,''))}</td><td>${num(p.current_qty??p.qty??0,0)}${p.mark_asof?`<small>估值至 ${esc(ny(p.mark_asof))}</small>`: ""}</td><td>${typeof p.target_weight==='number'?num(p.target_weight*100,2)+'%':'—'}</td><td title="${esc(skipped.get(p.code)||'')}">${esc(skipped.has(p.code)?'跳过 · '+reasonLabel(skipped.get(p.code)):processed.has(p.code)?decisionLabel(decisions.get(p.code)):p.side||p.action||'待执行计算')}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">当前空仓，等待下一完整信号</td></tr>'}</tbody></table></div><p class="subline">信号 ${esc(b.plan?.signal_date||b.plan?.source_date||s.signal_date||'—')} · 原目标现金 ${typeof b.plan?.target_cash_weight==='number'?num(b.plan.target_cash_weight*100,2)+'%':'—'}</p><p class="note">${esc(notes(b.reason||b.last_error||'数量按计划执行时行情和本账户资金计算。',b.status==='MISSED_OPEN'?b.connection_error:''))}</p></article>`;
  }).join('');
  renderChart(books);renderTrades();renderBroker(s.broker);
}
function renderTrades(){if(!snapshot)return;let trades=list(snapshot.trades);if(!trades.length)trades=bookRows(snapshot).flatMap(b=>list(b.trades||b.orders).map(t=>({strategy_id:b.strategy_id,...t})));const sid=$('trade-strategy').value,sym=$('trade-symbol').value.trim().toUpperCase();const shown=trades.filter(t=>(!sid||t.strategy_id===sid)&&(!sym||String(t.code).toUpperCase().includes(sym)));$('trades').innerHTML=shown.map(t=>`<tr><td>${esc(ny(t.filled_at||t.created_at))}</td><td>${esc(names[t.strategy_id]||t.strategy_id)}</td><td>${esc(t.signal_date)}</td><td>${esc(String(t.code||'').replace(/^US\./,''))}</td><td>${esc(t.side)}</td><td>${num(t.filled_qty??t.dealt_qty??t.qty,0)}</td><td>${num(t.fill_price??t.dealt_avg_price,4)}</td><td>${num(t.fee,4)}</td><td><span class="pill">${esc(label(t.status))}</span></td></tr>`).join('')||'<tr><td colspan="9" class="empty">尚无匹配成交；错过的开盘信号不会补记成交。</td></tr>';}
function renderChart(books){
  const series=books.map(b=>({id:b.strategy_id,points:list(b.nav_history).map(p=>({x:new Date(p.asof||p.time||p.date).getTime(),y:p.nav??(typeof p.equity==='number'?p.equity/(b.initial_cash||10000):NaN)})).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y))}));
  const pts=series.flatMap(s=>s.points),host=$('nav-chart');
  if(!pts.length){host.innerHTML='<span class="muted">起始净值 1.0000；等待第一笔开盘成交与行情计价记录。</span>';return;}
  const xs=pts.map(p=>p.x),ys=pts.map(p=>p.y),lo=Math.min(...ys,1),hi=Math.max(...ys,1),x0=Math.min(...xs),x1=Math.max(...xs),span=Math.max(hi-lo,.002);
  const width=Math.max(320,host.clientWidth),left=54,right=width-18,top=18,bottom=207;
  const low=lo-span*.1,high=hi+span*.1,x=v=>left+(v-x0)/Math.max(x1-x0,1)*(right-left),y=v=>bottom-(v-low)/(high-low)*(bottom-top);
  let svg=`<svg viewBox="0 0 ${width} 250" role="img" aria-label="三个纸面账户的实际净值路径"><title>纸面账户净值 · 真实记录时间</title><desc>按实际持仓和可核验报价计价，三个账户各自从净值1开始。不存在的日期和缺失估值没有补造。</desc>`;
  for(let i=0;i<4;i++){const value=low+(high-low)*i/3;svg+=`<line x1="${left}" x2="${right}" y1="${y(value)}" y2="${y(value)}" stroke="#e2e3dc"/><text x="${left-9}" y="${y(value)+4}" fill="#606770" font-size="11" text-anchor="end">${num(value,3)}</text>`;}
  svg+=`<line x1="${left}" x2="${right}" y1="${y(1)}" y2="${y(1)}" stroke="#939ba5" stroke-dasharray="3 5"/>`;
  for(const item of series)if(item.points.length){svg+=`<polyline fill="none" stroke="${colors[item.id]}" stroke-width="2.3" stroke-linejoin="round" points="${item.points.map(p=>x(p.x)+','+y(p.y)).join(' ')}"><title>${esc(names[item.id]||item.id)}</title></polyline>`;const p=item.points.at(-1);svg+=`<circle cx="${x(p.x)}" cy="${y(p.y)}" r="3.5" fill="${colors[item.id]}"><title>${esc(names[item.id]||item.id)} · ${num(p.y,4)} · ${esc(ny(p.x))}</title></circle>`;}
  const ticks=x0===x1?[x0]:[x0,x0+(x1-x0)/2,x1];
  for(let i=0;i<ticks.length;i++){const stamp=ticks[i],anchor=i===0?'start':i===ticks.length-1?'end':'middle';svg+=`<text x="${x(stamp)}" y="232" fill="#606770" font-size="11" text-anchor="${anchor}">${esc(new Intl.DateTimeFormat('zh-CN',{timeZone:'America/New_York',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(stamp)))}</text>`;}
  svg+='</svg>';host.innerHTML=svg;
}
function brokerWindow(b){
  const start=new Date(b.execution_time_utc||''),deadline=new Date(b.execution_deadline_utc||'');
  const seconds=b.execution_window_seconds;
  const end=Number.isFinite(deadline.getTime())?deadline:(Number.isFinite(start.getTime())&&typeof seconds==='number'?new Date(start.getTime()+seconds*1000):null);
  return Number.isFinite(start.getTime())&&end&&Number.isFinite(end.getTime())?`美东 ${ny(start)} → ${ny(end)}`:'执行窗口待核验';
}
function cooldownText(retryAt,start,end,running,now=Date.now()){
  if(Number.isFinite(end)&&end>0&&now>=end)return '本期执行窗口已结束，不再自动重试';
  const remaining=Math.max(0,Math.ceil((retryAt-now)/1000));
  if(!running)return remaining?`冷却剩余 ${remaining} 秒 · 自动执行暂停`:'冷却结束 · 自动执行暂停';
  if(Number.isFinite(start)&&start>0&&now<start)return '等待执行窗口';
  return remaining?`冷却剩余 ${remaining} 秒`:'冷却结束 · 等待最新合格卖一价';
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
  const attemptLabel=t.reprice_status==='ACKNOWLEDGED'?'已接收限价':t.reprice_status==='NOT_SENT'?'未发送限价':'待核对限价';
  const lastReprice=attempted?`${attemptLabel} $${num(t.last_reprice_limit,4)} · ${ny(t.last_reprice_at)}`:'尚未尝试改单';
  const repriceStatus=t.reprice_status&&t.reprice_status!=='NONE'?`<small>${esc(label(t.reprice_status))}</small>`:'';
  const retry=terminalBuy&&t.terminal_retry_after_utc?(latestBuy===t
    ?`<small>失败后重试 · ${cooldownMarkup(t.terminal_retry_after_utc,b)}</small>`
    :'<small>后续买单已另行记录</small>'):'';
  return `<tr><td>${esc(ny(t.filled_at||t.created_at))}</td><td>${esc(String(t.code||'').replace(/^US\./,''))}${t.order_id?`<small>券商委托号 ${esc(t.order_id)}</small>`:''}</td><td>${esc(t.side)}<small>${market?'市价单':'限价单'}</small></td><td>${num(t.qty,0)}</td><td>${pending&&!(typeof fillQty==='number'&&fillQty>0)?'待券商确认':num(fillQty,0)}</td><td>${pending&&!(typeof fillPrice==='number'&&fillPrice>0)?'待券商确认':num(fillPrice,4)}</td><td>${market?'—<small>市价单不改价；以实际成交均价为准</small>':`${esc(repriceCount)}<small>${esc(lastReprice)}</small>${repriceStatus}`}</td><td><span class="pill">${esc(label(t.status))}</span>${retry}</td></tr>`;
}
function brokerSkippedRows(b){
  return list(b.skipped).map(row=>`<div><strong>${esc(String(row.code||'').replace(/^US\./,''))}</strong> · ${esc(row.reason||'执行检查未通过')}${row.retry_after_utc?` · ${cooldownMarkup(row.retry_after_utc,b)}`:''}</div>`).join('');
}
function renderBroker(b){
  let panel=$('broker-panel');
  if(!b){if(panel)panel.remove();return;}
  if(!panel){panel=document.createElement('section');panel.id='broker-panel';panel.className='panel broker-panel';$('positions').before(panel);}
  const account=b.account||{},orders=list(b.orders||b.trades),positions=list(b.positions||account.positions).filter(p=>p.qty>0);
  const targets=list(b.plan?.rows||b.plan?.targets).filter(p=>typeof p.target_weight==='number'&&p.target_weight>0);
  const targetCash=b.plan?.target_cash_weight,cash=b.cash??b.strategy_cash,equity=b.equity??b.strategy_equity;
  const actualCash=typeof cash==='number'&&typeof equity==='number'&&equity>0?cash/equity:null;
  const reprice=b.reprice_policy||{},maxReprices=Number.isInteger(reprice.max_attempts_per_order)?reprice.max_attempts_per_order:null;
  const marketBuys=b.buy_order_type==='MARKET';
  const buyPolicy=marketBuys?'新买卖单采用市价单；先检查真实盘口、策略现金、可卖库存和股数，券商成交价与成交数量以对账为准。':'新买单采用限价单。';
  const amendPolicy=reprice.enabled===true&&reprice.mode==='SAME_BROKER_ORDER_ID'&&typeof reprice.interval_seconds==='number'&&maxReprices!==null
    ?`历史未成交限价单先对账；间隔 ${num(reprice.interval_seconds,0)} 秒沿用原券商委托号改单，单笔最多 ${num(maxReprices,0)} 次。市价单不改价。`
    :'改单规则待核验。';
  const terminalPolicy=reprice.enabled===true&&typeof reprice.terminal_retry_cooldown_seconds==='number'&&Number.isInteger(reprice.max_terminal_retries_per_code)
    ?`买单确认失败后冷却 ${num(reprice.terminal_retry_cooldown_seconds,0)} 秒，再核验最新报价及剩余量，以新客户端标识${marketBuys?'提交市价单':'提交限价单'}；单只最多 ${num(reprice.max_terminal_retries_per_code,0)} 次。`
    :'失败后重试规则待核验。';
  const runNote=b.status==='HALTED'?'自动执行已停止；当前不会改单或失败后重试，也不会补下旧信号。':b.running?'两种处理都只在有效执行窗口内进行；待对账不视作成交。':'自动执行暂停；当前不会改单或失败后重试。';
  const pending=orders.some(t=>['SUBMITTED','PENDING_RECONCILE','UNKNOWN','FILLED_PART'].includes(t.status));
  const latestBuy=new Map();
  for(const order of orders)if(order.side==='BUY'){
    const prior=latestBuy.get(order.code),created=Date.parse(order.created_at),priorCreated=Date.parse(prior?.created_at);
    if(!prior||!Number.isFinite(priorCreated)||Number.isFinite(created)&&created>=priorCreated)latestBuy.set(order.code,order);
  }
  panel.innerHTML=`<div class="panel-head"><div><h2>MOOMOO 模拟账户 · ${esc(names[b.strategy_id]||b.name||'策略待核验')}</h2><p class="muted">${esc(b.account_id||'账户待核验')} · <strong>本策略模拟本金 $${num(b.budget||10000,0)}</strong> · MOOMOO 账户总余额由券商预设，策略独立核算</p></div><span class="pill">${esc(label(b.status))}</span></div>
    <div class="broker-compare" aria-label="券商模拟目标与实际"><div><span>目标股票 / 已持有</span><strong>${targets.length||'—'} / ${positions.length}</strong><small>信号 ${esc(b.plan?.signal_date||'—')}；持仓以券商核验为准</small></div><div><span>目标现金 / 实际现金</span><strong>${typeof targetCash==='number'?num(targetCash*100,2)+'%':'—'} / ${typeof actualCash==='number'?num(actualCash*100,2)+'%':'—'}</strong><small>未完成买入的资金仍留在账户</small></div><div><span>策略模拟持仓市值</span><strong>$${typeof equity==='number'&&typeof cash==='number'?num(Math.max(0,equity-cash)):'—'}</strong><small>策略现金 $${num(cash)} · 策略净值 $${num(equity)}</small></div><div><span>委托记录 / 确认成交</span><strong>${num(b.order_count??orders.length,0)} / ${num(orders.filter(t=>['FILLED_ALL','FILLED_PART'].includes(t.status)).length,0)}</strong><small>按每笔订单类型和券商回报记录</small></div></div>
    <p class="broker-window">本期执行窗口：${esc(brokerWindow(b))} · 本期目标 ${targets.length||'—'} 只股票</p>
    <p class="broker-policy"><span class="policy-label">新买单</span> ${esc(buyPolicy)}<br><span class="policy-label">有效委托</span> ${esc(amendPolicy)}<br><span class="policy-label">确认失败</span> ${esc(terminalPolicy)}<br><strong>${esc(runNote)}</strong></p>
    <p class="status-note">${esc(notes(b.reason||b.last_error||'等待计划执行时点；自动买卖仅限此模拟账户。',b.status==='MISSED_OPEN'?b.last_error:''))}</p>
    ${pending?'<p class="broker-pending">券商委托仍需对账；只计入已确认的成交数量，待确认部分不记为成交。</p>':''}
    ${list(b.skipped).length?'<div class="broker-skips"><strong>本期未执行股票</strong>'+brokerSkippedRows(b)+'</div>':''}
    <div class="table-wrap"><table><thead><tr><th>记录时间 · 纽约</th><th>股票 / 委托号</th><th>动作</th><th>委托股数</th><th>确认成交股数</th><th>确认成交均价</th><th>改单尝试次数 / 最近报价</th><th>券商状态</th></tr></thead><tbody>${orders.map(t=>brokerOrderRow(t,maxReprices,b,latestBuy.get(t.code))).join('')||'<tr><td colspan="8" class="empty">尚未向券商发送委托</td></tr>'}</tbody></table></div>`;
}
async function refresh(){try{render(await api('/api/applied/state'));error('');}catch(e){error(e.message);}}
async function refreshBroker(){if(busy)return;busy=true;$('refresh').disabled=true;try{if(snapshot?.broker&&!snapshot.broker.running)await api('/api/applied/reconcile',{});await refresh();}catch(e){error(e.message);}finally{busy=false;$('refresh').disabled=false;if(snapshot)render(snapshot);}}
async function action(name){busy=true;try{await api('/api/applied/'+name,{});await refresh();}catch(e){error(e.message);}finally{busy=false;if(snapshot)render(snapshot);}}
$('refresh').addEventListener('click',refreshBroker);for(const name of ['start','stop','halt'])$(name).addEventListener('click',()=>action(name));$('trade-strategy').addEventListener('change',renderTrades);$('trade-symbol').addEventListener('input',renderTrades);refresh();setInterval(refresh,15000);setInterval(updateCooldowns,1000);

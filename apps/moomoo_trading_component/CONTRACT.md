# Implementation contract

Standalone Python 3.11+ package `moomoo_component`, standard-library server and core.
No live order or unlock capability. Default offline paper mode; manual Moomoo read-only probe; explicit simulator account required for broker simulation. OpenD loopback port 18441 from provided screenshot. US stock/ETF only in v1.

## Broker interface (brokers.py)

`MoomooBroker(host='127.0.0.1', port=18441, security_firm='FUTUSECURITIES', account_id=None)`
- `probe() -> dict`: connectivity + SDK version + ONLY simulation STOCK or STOCK_AND_OPTION account list; each traded instrument must independently validate as STOCK/ETF, never derivatives. No live balances/ids exposed. Accounts `{account_id: str, market: 'US', environment:'SIMULATE'}`. No trading unlock.
- `snapshot(codes: list[str]) -> dict`: requires explicit simulation account, validate same account SIMULATE/(STOCK or STOCK_AND_OPTION)/US/ACTIVE each time. `{cash:float, equity:float, positions:{code:{qty:int,sellable:int,market_value:float}}, quotes:{code:{price:float,bid:float,ask:float,asof:UTC ISO str,lot_size:int,price_tick:float,tradable:bool}}, open_orders:list}`. Cash must be nonmargin USD net cash bounded by USD cash, all values finite. Unsupported holdings fail closed. Query server refresh; detect RTH via official market state; timestamps in New York converted with zoneinfo. No stale-time refreshing. Open orders may include all nonterminal account orders. No silent zero fallback for missing funds. Get quotes for passed codes plus held positions.
- `submit(order:dict, client_id:str) -> dict`: assert validated simulation account on EVERY submission, explicit `TrdEnv.SIMULATE`, `acc_id`, limit normal order, DAY, no outside RTH, session NONE. order `{code,side:'BUY'|'SELL',qty:int,limit_price:float}`; result `{order_id:str,status:str}`. Exception means unknown; engine latches halt, never retries automatically. No credentials stored.
- `close()` closes contexts.
- SDK lazy import, core runs without moomoo. injectable SDK optional for tests. No network during import.

## Strategy JSON v1

`{schema_version:1,strategy_id:'example',name:'...',revision:'1',asof:'2026-09-26T00:00:00Z',expires_at:'...',provenance:'demo'|'live'|'historical',targets:[{code:'US.AAPL',target_qty:1}],source:'optional text'}`
Strict unknown-key rejection. Zero means explicitly exit; omitted symbols untouched. Reject duplicate codes, invalid/future/expired timestamps, booleans or noninteger quantities, excessive targets. Import stores stale/historical manifests for review but execution rejects historical/expired. No arbitrary Python/plugin execution from uploads. Demo only paper.

## HTTP UI contract

GET `/api/state`: `{mode:'paper'|'moomoo_simulate',running:bool,halted:bool,halt_reason:str,active_strategy:str|null,strategies:[manifests],limits:dict,connection:dict,account:dict,orders:list,audit:list,preview:dict|null,last_error:str,live_enabled:false}`. Response JSON `{ok:true,data:...}`; errors `{ok:false,error:'...'}`.
GET `/api/token`: `{ok:true,data:{token:'...'}}`. POST requests same-origin JSON and `X-CSRF-Token` header; server checks Host/Origin and body size.
POST `/api/import` body `{manifest:object}`; `/api/switch` `{strategy_id}`; `/api/preview` `{}`; `/api/step` `{}`; `/api/start` `{}`; `/api/stop` `{}`; `/api/halt` `{}`; `/api/reset-halt` `{}`. reset only while stopped, unknown submissions prevent reset until reconciliation (v1 restart does NOT clear).
POST `/api/connect` `{port:18441,security_firm:'FUTUSECURITIES'}` read-only probe. `/api/mode` `{mode:'paper'}` or `{mode:'moomoo_simulate',account_id:'...',confirmation:'SIMULATE'}`; only when stopped, invalidates preview. `/api/demo` `{}` creates fresh demo strategy and offline synthetic paper quotes; demonstration only. `/api/limits` body supported numeric keys when stopped; engine validates. Mode switching forbidden with unresolved broker orders. `/api/reconcile` reads simulator status for pending/unknown (manual only, no resubmit).
State never connects implicitly. Read-only initial boot with no active strategy, no start, no mutation on GET except `/api/token`.

## UI ownership

Frontend files `moomoo_component/static/index.html`, `app.js`, `style.css` owned by UI agent. Chinese interface. Core/server/readme root agent. Broker files and broker tests broker agent.

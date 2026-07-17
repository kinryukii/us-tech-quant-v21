from dataclasses import dataclass,asdict

@dataclass
class TradeLedgerEvent:
 window_id:str;event_id:str;position_id:str;trade_date:str;ticker:str;side:str;shares:float;price:float;notional:float;normalized_notional:float;trade_reason:str;source_position_id:str|None;replacement_slot_id:str|None;pre_trade_cash:float;post_trade_cash:float;pre_trade_shares:float;post_trade_shares:float
 def to_dict(self): return asdict(self)

def validate_ledger(rows):
 ids=[x.event_id for x in rows]; buys=sum(x.normalized_notional for x in rows if x.side=='BUY');sells=sum(x.normalized_notional for x in rows if x.side=='SELL');return {'unique_event_ids':len(ids)==len(set(ids)),'turnover':buys+sells,'replacement_sources_ok':all(x.trade_reason!='VACANCY_ENTRY' or x.source_position_id for x in rows)}

from dataclasses import dataclass,asdict

@dataclass
class PositionLifecycle:
 window_id:str;position_id:str;ticker:str;entry_signal_date:str;entry_trade_date:str;entry_price:float;entry_rank:int;entry_reason:str;initial_weight:float;initial_shares:float;current_shares:float;holding_age_trading_days:int=0;exit_confirmation_count:int=0;weekly_exit_confirmation_count:int=0;last_weekly_check_date:str|None=None;hard_exit_flag:bool=False;exit_signal_date:str|None=None;exit_trade_date:str|None=None;exit_price:float|None=None;exit_rank:int|None=None;exit_reason:str|None=None;realized_return:float|None=None;closed_flag:bool=False;censored_at_window_end:bool=False
 def to_dict(self): return asdict(self)

def validate_positions(rows):
 ids=[x.position_id for x in rows];return len(ids)==len(set(ids)) and all(x.holding_age_trading_days>=0 for x in rows)

from dataclasses import dataclass
@dataclass
class PersistenceRuleConfig:
 entry_rank_threshold:int=5;exit_rank_threshold:int=10;min_hold_days:int=0;daily_exit_confirmation_days:int=1;weekly_check_enabled:bool=False;weekly_exit_confirmation_weeks:int=1;hard_exit_bypass_enabled:bool=True
def rank_exit(p,rank,cfg,hard=False):
 if hard and cfg.hard_exit_bypass_enabled:return True,'HARD_EXIT_FIXTURE'
 if p.holding_age_trading_days<cfg.min_hold_days:return False,None
 p.exit_confirmation_count=p.exit_confirmation_count+1 if rank>cfg.exit_rank_threshold else 0
 return p.exit_confirmation_count>=cfg.daily_exit_confirmation_days,('CONFIRMED_RANK_EXIT' if cfg.daily_exit_confirmation_days>1 else 'RANK_EXIT')

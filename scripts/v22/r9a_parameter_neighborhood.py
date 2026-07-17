def evaluate_neighborhood(group,rows):
 if len(rows)<2:return {'neighborhood_group':group,'neighborhood_support':'INSUFFICIENT_DATA'}
 ok=all(r.get('median_excess',-1)>=0 and r.get('turnover_reduction_vs_base',0)>0 and r.get('drawdown_delta',0)>=-.02 for r in rows)
 return {'neighborhood_group':group,'neighborhood_support':bool(ok)}

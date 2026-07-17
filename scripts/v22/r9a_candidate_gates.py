def evaluate_gate(variant,observed,op,threshold,name):
 import math
 ok=False if observed is None or (isinstance(observed,float) and math.isnan(observed)) else {'>':observed>threshold,'>=':observed>=threshold,'<=':observed<=threshold}.get(op,False)
 return {'variant':variant,'gate':name,'observed_value':observed,'required_operator':op,'required_threshold':threshold,'pass_fail':'PASS' if ok else 'FAIL','failure_reason':'' if ok else ('NOT_RUN_OR_NAN' if observed is None or (isinstance(observed,float) and math.isnan(observed)) else 'THRESHOLD_NOT_MET')}

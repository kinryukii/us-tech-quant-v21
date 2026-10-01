import unittest
import numpy as np
import torch
from joint_neural_v2 import project, execute_targets, JointPolicy, Market, FEATURES


class HoldingTrainingTests(unittest.TestCase):
    def test_locked_units_and_capital_are_preserved(self):
        units=torch.tensor([.4,0.],dtype=torch.float64)
        action=project(torch.tensor([4.]),max_names=19,max_exposure=.55)
        target=torch.tensor([.4,float(action[0])],dtype=torch.float64)
        u,c,fees,nav,blocks=execute_targets(units,torch.tensor(.6),torch.tensor([2.,1.]),
            torch.tensor([True,True]),target,torch.tensor([True,False]),torch.tensor([False,True]))
        self.assertEqual(float(u[0]),.4)
        self.assertAlmostEqual(float(c+(u*torch.tensor([2.,1.])).sum()+fees),float(nav),places=7)
        self.assertEqual(blocks,0)

    def test_unexpected_sell_failure_cannot_create_21st_holding(self):
        units=torch.tensor([.025]*20+[0.],dtype=torch.float64)
        target=torch.tensor([0.]*20+[.1],dtype=torch.float64)
        fill=torch.tensor([False]*20+[True])
        u,c,fees,nav,blocks=execute_targets(units,torch.tensor(.5),torch.ones(21),fill,target,
            torch.zeros(21,dtype=torch.bool),torch.ones(21,dtype=torch.bool))
        self.assertEqual(int((u>0).sum()),20)
        self.assertEqual(float(u[-1]),0.)
        self.assertEqual(blocks,1)
        self.assertEqual(float(c),.5)

    def test_projection_uses_residual_capacity(self):
        w=project(torch.ones(40),max_names=5,max_exposure=.18)
        self.assertEqual(int((w>0).sum()),5)
        self.assertLessEqual(float(w.sum()),.1800001)
        self.assertEqual(float(project(torch.ones(5),max_names=0,max_exposure=0).sum()),0.)

    def test_next_open_failure_never_changes_signal_targets(self):
        torch.manual_seed(5)
        policy=JointPolicy()
        market=Market.__new__(Market)
        market.tickers=['OLD','NEW'];market.lookup={'OLD':0,'NEW':1}
        # First day buys OLD; second day only NEW has an input, so OLD is reserved.
        def day(idx,date,fill):
            return dict(date=date,ids=torch.tensor([idx]),x=torch.zeros(1,len(FEATURES)),
                eligible=torch.tensor([True]),close=torch.ones(2,dtype=torch.float64),
                signal_price_usable=torch.tensor([True,True]),opening=torch.ones(2,dtype=torch.float64),
                ending=torch.ones(2,dtype=torch.float64),fill=torch.tensor(fill),vol=torch.tensor([.02]))
        market.days=[day(0,'2025-01-02',[True,True]),day(1,'2025-01-03',[True,True])]
        _,before=market.episode(policy)
        market.days[-1]['fill']=torch.tensor([False,False])
        _,after=market.episode(policy)
        self.assertGreater(before[-1]['reserved_missing_or_restricted_names'],0)
        for key in ['target_exposure','target_names','reserved_weight','reserved_missing_or_restricted_names']:
            self.assertEqual(before[-1][key],after[-1][key])


if __name__=='__main__':unittest.main()

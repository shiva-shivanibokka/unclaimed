import time, warnings; warnings.filterwarnings("ignore")
from policyengine_us import Simulation
exec(open("household_basics.py").read().split("outs=")[0])
Simulation(situation=hh(30000))  # warm
for outs in (["snap"],["eitc"],["snap","eitc","ctc","wic","medicaid","chip"]):
    t=time.time(); s=Simulation(situation=hh(30000,"CA"))
    for o in outs: s.calculate(o,Y if o not in("snap","wic") else f"{Y}-01")
    print(outs, f"{time.time()-t:.2f}s")
# axes: vary income 0..60000 in 25 steps in ONE sim
sit=hh(30000,"CA"); sit["axes"]=[[{"name":"employment_income","count":25,"min":0,"max":60000,"period":Y}]]
t=time.time(); s=Simulation(situation=sit)
snap=s.calculate("snap",f"{Y}-01")*12; eitc=s.calculate("eitc",Y)
print("axes 25 pts", f"{time.time()-t:.2f}s")
print("SNAP by income:", [int(x) for x in snap])

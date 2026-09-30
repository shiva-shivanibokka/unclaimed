import time, warnings, copy; warnings.filterwarnings("ignore")
from policyengine_us import Simulation
exec(open("household_basics.py").read().split("outs=")[0])
P={"snap":f"{Y}-01","wic":f"{Y}-01","eitc":Y,"ctc":Y,"medicaid":Y,"chip":Y,"ca_eitc":Y,"ca_care":Y,"aca_ptc":Y}
s=Simulation(situation=hh(30000)); [s.calculate(k,p) for k,p in P.items()]  # warm everything
for k,p in P.items():
    ts=[]
    for inc in (21000,29000,37000):
        t=time.time(); Simulation(situation=hh(inc)).calculate(k,p); ts.append(time.time()-t)
    print(f"{k:10} warm {min(ts)*1000:.0f}-{max(ts)*1000:.0f} ms")
t=time.time(); s=Simulation(situation=hh(31000)); [s.calculate(k,p) for k,p in P.items()]; print("all 9 programs, 1 household", f"{(time.time()-t)*1000:.0f} ms")
# batch: 16 variant households in one simulation
def batch(n):
    sit={"people":{},"tax_units":{},"spm_units":{},"families":{},"marital_units":{},"households":{}}
    for i in range(n):
        h=hh(20000+i*2000)
        for g in sit:
            for k,v in h[g].items():
                v=copy.deepcopy(v)
                if "members" in v: v["members"]=[f"{m}_{i}" for m in v["members"]]
                sit[g][f"{k}_{i}"]=v
    return sit
for n in (8,16,32):
    t=time.time(); s=Simulation(situation=batch(n)); [s.calculate(k,p) for k,p in P.items()]; print(f"batch {n} households x 9 programs", f"{(time.time()-t)*1000:.0f} ms")

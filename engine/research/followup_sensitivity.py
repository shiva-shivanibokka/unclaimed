import warnings, copy; warnings.filterwarnings("ignore")
from policyengine_us import Simulation
exec(open("household_basics.py").read().split("outs=")[0])
P={"snap":f"{Y}-01","wic":f"{Y}-01","eitc":Y,"ctc":Y,"ca_eitc":Y,"medicaid":Y,"chip":Y,"aca_ptc":Y,"ca_tanf":Y}
def base(inc):
    s=hh(inc,"CA"); s["households"]["h"]["county"]={Y:"LOS_ANGELES_COUNTY_CA"}; return s
def run(sit):
    s=Simulation(situation=sit); out={}
    for k,p in P.items():
        v=s.calculate(k,p); 
        if k=="medicaid" or k=="chip": out[k]=int((v>0).sum())   # people covered
        else: out[k]=round(float(v.sum())*(12 if k in("snap","wic") else 1))
    return out
def setv(sit,path,var,val):
    s=copy.deepcopy(sit); g,e=path; s[g][e][var]={Y:val}; return s
cands=[("Child care costs $0 vs $12,000/yr",("spm_units","s"),"childcare_expenses",0,12000),
       ("Pays heating/cooling: no vs $1,800/yr",("spm_units","s"),"heating_cooling_expense",0,1800),
       ("Pregnant: no vs yes",("people","mom"),"is_pregnant",False,True),
       ("Job health insurance: no vs yes",("people","mom"),"has_esi",False,True),
       ("Savings $0 vs $15,000",("spm_units","s"),"spm_unit_assets",0,15000),
       ("Child support $0 vs $6,000/yr",("people","mom"),"child_support_received",0,6000),
       ("Mom's status: citizen vs undocumented",("people","mom"),"immigration_status","CITIZEN","UNDOCUMENTED")]
for inc in (32000,48000):
    b=base(inc); print(f"\n=== Maria at ${inc:,} (LA County). Baseline:",run(b))
    for label,path,var,lo,hi in cands:
        a,c=run(setv(b,path,var,lo)),run(setv(b,path,var,hi))
        diff={k:(a[k],c[k]) for k in P if a[k]!=c[k]}
        print(f"  {label:42} ->", diff if diff else "NO CHANGE")

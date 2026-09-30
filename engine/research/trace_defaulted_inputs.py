import warnings, time; warnings.filterwarnings("ignore")
from policyengine_us import Simulation
exec(open("household_basics.py").read().split("outs=")[0])
s=Simulation(situation=hh(32000,"CA")); s.trace=True
progs={"snap":f"{Y}-01","wic":f"{Y}-01","eitc":Y,"ctc":Y,"medicaid":Y,"chip":Y,"ca_eitc":Y,"aca_ptc":Y,"ca_tanf":Y}
t=time.time()
for k,p in progs.items(): s.calculate(k,p)
print("traced calc", round(time.time()-t,2),"s")
tb=s.tax_benefit_system
touched=set(n for (n,_p) in s.tracer._computation_log if False) if False else set()
# collect all variable names computed during trace
def walk(node):
    touched.add(node.name)
    for c in node.children: walk(c)
for root in s.tracer.trees: walk(root)
inputs=[v for v in touched if not tb.variables[v].formulas and not getattr(tb.variables[v],'adds',None) and not getattr(tb.variables[v],'subtracts',None)]
given={"age","employment_income","rent","state_name"}
defaulted=sorted(v for v in inputs if v not in given)
print("variables touched:",len(touched),"| input vars read:",len(inputs),"| defaulted (not provided):",len(defaulted))
print(defaulted[:200])

import time
from policyengine_us import Simulation, CountryTaxBenefitSystem
Y=2026
def hh(income, state="CA", rent=18000, kid_ages=(4,9)):
    people={"mom":{"age":{Y:32},"employment_income":{Y:income},"rent":{Y:rent}}}
    for i,a in enumerate(kid_ages): people[f"k{i}"]={"age":{Y:a}}
    m=list(people)
    return {"people":people,"tax_units":{"t":{"members":m}},"spm_units":{"s":{"members":m}},
            "families":{"f":{"members":m}},"marital_units":{"mu":{"members":["mom"]}, **{f"mu{i}":{"members":[f"k{i}"]} for i in range(len(kid_ages))}},
            "households":{"h":{"members":m,"state_name":{Y:state}}}}
outs=["eitc","ctc","snap","wic","medicaid","chip","ca_eitc","ca_care","il_liheap","household_benefits","household_refundable_tax_credits"]
for inc in [20000,27000,32000,33000,45000]:
  for st in ["CA","IL"]:
    t=time.time(); s=Simulation(situation=hh(inc,st)); r={}
    for o in outs:
        try:
            v=s.calculate(o,Y) if o not in("snap","wic") else s.calculate(o,f"{Y}-01")*12
            r[o]=round(float(v.sum()))
        except Exception as e: r[o]="n/a"
    print(inc,st,f"{time.time()-t:.2f}s",r)

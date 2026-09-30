import warnings; warnings.filterwarnings("ignore")
from policyengine_us import Simulation
Y=2026
def single(age,inc,county,st="CA",kids=()):
    ppl={"a":{"age":{Y:age},"employment_income":{Y:inc}}}
    for i,k in enumerate(kids): ppl[f"k{i}"]={"age":{Y:k}}
    m=list(ppl)
    h={"members":m,"state_name":{Y:st}}
    if county: h["county"]={Y:county}
    return Simulation(situation={"people":ppl,"tax_units":{"t":{"members":m}},"spm_units":{"s":{"members":m}},"families":{"f":{"members":m}},"households":{"h":h}})
print("ACA premium credit, single 55yo, $45K:")
for c in [None,"LOS_ANGELES_COUNTY_CA","ALAMEDA_COUNTY_CA","MODOC_COUNTY_CA","SAN_FRANCISCO_COUNTY_CA"]:
    print("  ",c or "(not given → default)", round(float(single(55,45000,c).calculate("aca_ptc",Y)[0])))
print("CalWORKs cash, parent + 2 kids, $6K/yr:")
for c in [None,"LOS_ANGELES_COUNTY_CA","FRESNO_COUNTY_CA","SAN_FRANCISCO_COUNTY_CA"]:
    print("  ",c or "(not given → default)", round(float(single(30,6000,c,kids=(3,6)).calculate("ca_tanf",Y).sum())))
print("IL TANF cash, parent + 2 kids, $6K/yr:")
for c in [None,"COOK_COUNTY_IL","ADAMS_COUNTY_IL","CHAMPAIGN_COUNTY_IL"]:
    print("  ",c or "(not given → default)", round(float(single(30,6000,c,"IL",kids=(3,6)).calculate("il_tanf",Y).sum())))

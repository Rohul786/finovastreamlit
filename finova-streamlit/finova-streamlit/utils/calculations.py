from math import pow

def sip_projection(monthly, rate, years, step_up=0, inflation=6):
    rows=[]; corpus=0; invested=0; current=monthly; mr=rate/100/12
    for y in range(1, years+1):
        for _ in range(12):
            corpus=(corpus+current)*(1+mr); invested+=current
        rows.append({'Year':y,'Invested':round(invested),'Corpus':round(corpus),'Wealth Gained':round(corpus-invested),'Real Value':round(corpus/pow(1+inflation/100,y))})
        current*=1+step_up/100
    return rows

def required_monthly(target,current,months,annual_return=7):
    remaining=max(0,target-current)
    if remaining<=0:return 0
    if annual_return<=0:return round(remaining/max(1,months))
    r=annual_return/100/12
    return round(remaining*r/((1+r)**months-1))

def health_score(income,expenses,goals,categories):
    if income<=0:return 50,'C','Income Not Specified'
    savings=max(0,income-expenses); savings_score=min(100,round((savings/income*100)/35*100))
    under=sum(c['spent']<=c['allocated'] for c in categories); budget=round(under/max(1,len(categories))*100)
    gt=sum(g['target'] for g in goals); gc=sum(g['current'] for g in goals); goal=min(100,round(gc/gt*100)) if gt else 70
    cash=max(0,min(100,round(100-((expenses/income*100)-40)*1.5)))
    score=round(savings_score*.35+budget*.25+goal*.2+cash*.2)
    grade='A+' if score>=85 else 'A' if score>=75 else 'B' if score>=60 else 'C' if score>=45 else 'D'
    text={'A+':'Exceptional Financial Health','A':'Strong Financial Discipline','B':'Healthy with Room to Optimize','C':'Requires Budget Rebalancing','D':'High Financial Vulnerability'}[grade]
    return score,grade,text

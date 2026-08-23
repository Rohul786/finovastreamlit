import os, re, json, math, hmac, hashlib, secrets, sqlite3, smtplib, ssl
from datetime import datetime, date, timedelta
from email.message import EmailMessage
from pathlib import Path
import requests
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
BASE = Path(__file__).parent
DB_PATH = BASE / 'finova.db'
CURRENCIES = {'INR':'₹','USD':'$','EUR':'€','GBP':'£'}
PAYMENT_METHODS=['UPI','Credit Card','Debit Card','Net Banking','PayPal','Cash','Crypto']
CATEGORIES=['Food & Dining','Rent & Housing','Education','Entertainment','Utilities','Transportation','Shopping','Health & Fitness','Investments & Savings','Salary','Freelance','Gifts & Rewards','Miscellaneous']
GOAL_CATEGORIES=['Safety','Tech & Career','Education','Travel','Wealth','Lifestyle','Other']
RISK_OPTIONS=['Conservative','Moderate','Aggressive']

with open(BASE/'stock_data.json',encoding='utf-8') as f: MARKET=json.load(f)
with open(BASE/'initial_data.json',encoding='utf-8') as f: INITIAL=json.load(f)
INITIAL_CATEGORIES=INITIAL['INITIAL_CATEGORIES']; INITIAL_TRANSACTIONS=INITIAL['INITIAL_TRANSACTIONS']; INITIAL_GOALS=INITIAL['INITIAL_GOALS']; INITIAL_RISK_PROFILE=INITIAL['INITIAL_RISK_PROFILE']

DEFAULT_PROFILE={
 'name':'Investor','email':'','phone':'','age':24,'occupation':'Investor','city':'Bengaluru, Karnataka',
 'monthlyIncome':65000,'monthlyBudgetCap':38000,'monthlySipTarget':18000,'currency':'INR','emergencyFundMonths':6,
 'targetSavingsRate':35,'riskTolerance':'Moderate','avatarUrl':'','appLogoUrl':'assets/finova-logo.svg','isLoggedIn':False,
 'isVerified':False,'kycStatus':'not_started','kycData':None
}

# ---------------- persistence ----------------
def db():
    c=sqlite3.connect(DB_PATH,check_same_thread=False)
    c.row_factory=sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS accounts(email TEXT PRIMARY KEY, name TEXT, phone TEXT, password TEXT, profile TEXT, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS workspace(email TEXT PRIMARY KEY, categories TEXT, transactions TEXT, goals TEXT, risk TEXT, profile TEXT)''')
    c.commit(); return c
DB=db()

def hash_password(p): return 'sha256:'+hashlib.sha256(p.encode()).hexdigest()
def verify_password(p,h): return bool(p and h) and h == hash_password(p) if h.startswith('sha256:') else h==p

def save_account(profile,password):
    email=profile['email'].strip().lower(); ph=hash_password(password)
    DB.execute('INSERT OR REPLACE INTO accounts VALUES(?,?,?,?,?,?)',(email,profile.get('name',''),profile.get('phone',''),ph,json.dumps(profile),datetime.utcnow().isoformat())); DB.commit()

def account(email):
    value=email.strip()
    if '@' in value:
        r=DB.execute('SELECT * FROM accounts WHERE email=?',(value.lower(),)).fetchone()
    else:
        digits=re.sub(r'\D','',value)
        r=DB.execute("SELECT * FROM accounts WHERE replace(replace(replace(phone,' ',''),'-',''),'+' ,'') LIKE ?",('%'+digits,)).fetchone() if digits else None
    return dict(r) if r else None

def save_workspace(email, categories=None, transactions=None, goals=None, risk=None, profile=None):
    email=email.lower().strip(); old=DB.execute('SELECT * FROM workspace WHERE email=?',(email,)).fetchone()
    vals={k:(json.loads(old[k]) if old and old[k] else None) for k in ['categories','transactions','goals','risk','profile']}
    vals.update({k:v for k,v in [('categories',categories),('transactions',transactions),('goals',goals),('risk',risk),('profile',profile)] if v is not None})
    DB.execute('INSERT OR REPLACE INTO workspace VALUES(?,?,?,?,?,?)',(email,json.dumps(vals['categories'] or INITIAL_CATEGORIES),json.dumps(vals['transactions'] or INITIAL_TRANSACTIONS),json.dumps(vals['goals'] or INITIAL_GOALS),json.dumps(vals['risk'] or INITIAL_RISK_PROFILE),json.dumps(vals['profile'] or {}))); DB.commit()

def load_workspace(email):
    r=DB.execute('SELECT * FROM workspace WHERE email=?',(email.lower().strip(),)).fetchone()
    if not r: return [json.loads(json.dumps(x)) for x in INITIAL_CATEGORIES],[json.loads(json.dumps(x)) for x in INITIAL_TRANSACTIONS],[json.loads(json.dumps(x)) for x in INITIAL_GOALS],json.loads(json.dumps(INITIAL_RISK_PROFILE))
    return json.loads(r['categories']),json.loads(r['transactions']),json.loads(r['goals']),json.loads(r['risk'])

# ---------------- formatting / calculations ----------------
def money(x,c='INR'):
    s=CURRENCIES.get(c,'₹'); x=float(x or 0); sign='-' if x<0 else ''; x=abs(x)
    if c=='INR': return f'{sign}{s}{x:,.0f}'
    return f'{sign}{s}{x:,.2f}'
def compact(x,c='INR'):
    s=CURRENCIES.get(c,'₹'); x=float(x or 0); sign='-' if x<0 else ''; x=abs(x)
    if x>=1e7: return f'{sign}{s}{x/1e7:.2f} Cr'
    if x>=1e5: return f'{sign}{s}{x/1e5:.2f} L'
    if x>=1e3: return f'{sign}{s}{x/1e3:.1f}K'
    return f'{sign}{s}{x:,.0f}'
def pct(x): return f'{x:.2f}%'
def fdate(s):
    try:return datetime.fromisoformat(str(s)).strftime('%d %b %Y')
    except:return str(s)

def monthly_stats(txs):
    m=datetime.now().strftime('%Y-%m')
    cur=[t for t in txs if str(t.get('date','')).startswith(m)]
    income=sum(t['amount'] for t in cur if t['type']=='income'); exp=sum(t['amount'] for t in cur if t['type']=='expense'); inv=sum(t['amount'] for t in cur if t['type']=='investment')
    net=income-exp-inv; return {'income':income,'expenses':exp,'investments':inv,'netSavings':net,'savingsRate':(net/income*100 if income else 0)}

def health_score(profile,cats,goals):
    stt=monthly_stats(st.session_state.transactions); income=max(1,stt['income'] or profile.get('monthlyIncome',65000)); expenses=stt['expenses']
    savings=max(0,income-expenses); sr=savings/income*100; savings_score=min(100,round(sr/35*100))
    total_alloc=sum(c['allocated'] for c in cats); total_spent=sum(c['spent'] for c in cats); budget_score=max(0,min(100,round((1-total_spent/max(1,total_alloc))*100)))
    gt=sum(g['targetAmount'] for g in goals); gc=sum(g['currentAmount'] for g in goals); goal_score=min(100,round(gc/gt*100)) if gt else 70
    ratio=expenses/income*100; cash=max(0,min(100,round(100-(ratio-40)*1.5)))
    overall=round(savings_score*.35+budget_score*.25+goal_score*.2+cash*.2)
    if overall>=85: grade,r='A+','Exceptional Financial Health'
    elif overall>=75: grade,r='A','Strong Financial Discipline'
    elif overall>=60: grade,r='B','Healthy with Room to Optimize'
    elif overall>=45: grade,r='C','Requires Budget Rebalancing'
    else: grade,r='D','High Financial Vulnerability'
    return {'score':overall,'grade':grade,'ratingText':r,'breakdown':{'Savings Rate':savings_score,'Budget Discipline':budget_score,'Goal Progress':goal_score,'Cashflow':cash}}

def sip_projection(monthly,rate,years,initial=0):
    mr=rate/100/12; rows=[]; corpus=initial
    for y in range(1,years+1):
        for _ in range(12): corpus=corpus*(1+mr)+monthly
        rows.append({'Year':y,'Corpus':corpus,'Invested':initial+monthly*12*y,'Returns':corpus-(initial+monthly*12*y)})
    return pd.DataFrame(rows)

def goal_monthly(target,current,target_date,annual=10):
    months=max(1,round((date.fromisoformat(target_date)-date.today()).days/30.4375)); r=annual/100/12; rem=max(0,target-current)
    if r==0:return round(rem/months)
    return round(rem*r/((1+r)**months-1))

# ---------------- AI / fallbacks ----------------
def parse_expense_fallback(text):
    low=text.lower(); m=re.search(r'(?:₹|rs\.?|inr)?\s*(\d+(?:,\d+)*(?:\.\d+)?)',text,re.I); amount=float(m.group(1).replace(',','')) if m else 250
    title=re.sub(r'(\d+(?:\.\d+)?)','',text); title=re.sub(r'(₹|rs\.?|inr|paid|spent|received|for|on|via|using)','',title,flags=re.I).strip().title() or 'Quick Transaction'
    typ='income' if any(x in low for x in ['salary','freelance','stipend','received','credited','cashback','dividend']) else 'expense'
    if 'freelance' in low: cat='Freelance'
    elif 'salary' in low: cat='Salary'
    elif any(x in low for x in ['rent','maintenance','landlord']): cat='Rent & Housing'
    elif any(x in low for x in ['uber','ola','fuel','petrol','metro','cab','auto','flight']): cat='Transportation'
    elif any(x in low for x in ['book','course','tuition','udemy','college','fee']): cat='Education'
    elif any(x in low for x in ['movie','netflix','spotify','game','concert','prime']): cat='Entertainment'
    elif any(x in low for x in ['electricity','wifi','broadband','water','gas','recharge','bill']): cat='Utilities'
    elif any(x in low for x in ['amazon','myntra','flipkart','zara','clothes','shopping']): cat='Shopping'
    elif any(x in low for x in ['medicine','doctor','pharmacy','gym','hospital']): cat='Health & Fitness'
    elif any(x in low for x in ['sip','mutual fund','stock','zerodha','groww','shares']): cat='Investments & Savings'
    else: cat='Food & Dining'
    pm='PayPal' if 'paypal' in low else 'Credit Card' if any(x in low for x in ['credit','visa','mastercard','amex']) else 'Debit Card' if any(x in low for x in ['debit','rupay']) else 'Cash' if any(x in low for x in ['cash','wallet']) else 'Net Banking' if any(x in low for x in ['netbanking','net banking','hdfc','sbi','icici','axis','neft','rtgs','imps']) else 'UPI'
    return {'title':title,'amount':amount,'type':typ,'category':cat,'paymentMethod':pm,'notes':f'Quick entry parsed from text: "{text}"'}

def portfolio_fallback(profile,risk,surplus):
    surplus=surplus if surplus>0 else 15000; r=risk.get('category','Moderate').lower()
    if 'aggressive' in r or 'growth' in r:
        name='High Growth Alpha Portfolio'; rationale='Optimized for long-term compound capital appreciation with a high equity focus and strategic sector rotation.'
        a=[('Large & Mid Cap Index Funds',50,'High Growth','13-15% CAGR'),('Small Cap Equity Funds',20,'Very High Growth','16-18% CAGR'),('Global & US Tech Equities',15,'High Growth','14-16% CAGR'),('Sovereign Gold Bonds / Gold ETFs',10,'Hedge','9-11% CAGR'),('Liquid Emergency Reserves',5,'Capital Preservation','6-7% CAGR')]
    elif 'conservative' in r:
        name='Capital Shield & Steady Income Plan'; rationale='Focused on capital preservation, steady fixed yields, and low volatility with a disciplined inflation hedge.'
        a=[('High Yield Corporate Debt & FDs',40,'Low Risk','7.0-7.8% CAGR'),('Large Cap Nifty 50 Index Fund',25,'Moderate Growth','11-13% CAGR'),('Liquid & Overnight Funds',20,'Capital Preservation','6.0-6.5% CAGR'),('Sovereign Gold Bonds',15,'Hedge','9-10% CAGR')]
    else:
        name='Finova Smart Balanced Growth Strategy'; rationale='Mathematically balanced 60/40 equity-debt strategy optimizing risk-adjusted returns while building a solid emergency reserve.'
        a=[('Large & Mid Cap Index Funds (Nifty 50/Next 50)',45,'High Growth','12-14% CAGR'),('Short Duration Debt & Fixed Deposits',25,'Low Risk','6.5-7.5% CAGR'),('Emergency Liquid Fund',15,'Capital Preservation','5.5-6.5% CAGR'),('Sovereign Gold Bonds / Gold ETFs',10,'Hedge','9-11% CAGR'),('Global & Flexi Cap Equities',5,'High Growth','13-15% CAGR')]
    alloc=[{'asset':x[0],'percentage':x[1],'monthlyAmount':round(surplus*x[1]/100),'riskLevel':x[2],'expectedReturn':x[3]} for x in a]
    return {'portfolioName':name,'rationale':rationale,'allocations':alloc,'projected5YearCorpus':round(surplus*12*5*1.38),'projected10YearCorpus':round(surplus*12*10*2.25),'keyPrinciples':['Automate SIP transfers on the 1st of every month right after salary credit.','Rebalance asset allocation bi-annually if equity diverges by >5% from target weights.','Lock in at least 6 months of living expenses in liquid funds before increasing satellite exposure.']}

def ai_generate(prompt, system='', json_mode=False, model=None):
    key=os.getenv('GEMINI_API_KEY')
    if key:
        try:
            from google import genai
            client=genai.Client(api_key=key)
            resp=client.models.generate_content(model=model or 'gemini-2.5-flash', contents=prompt, config={'system_instruction':system,'temperature':0.4,'response_mime_type':'application/json' if json_mode else 'text/plain'})
            text=getattr(resp,'text','') or ''
            return json.loads(text) if json_mode else text
        except Exception: pass
    return None

def send_email(to,subject,text,html=None):
    resend=os.getenv('RESEND_API_KEY')
    if resend:
        try:
            r=requests.post('https://api.resend.com/emails',headers={'Authorization':f'Bearer {resend}','Content-Type':'application/json'},json={'from':os.getenv('EMAIL_FROM','onboarding@resend.dev'),'to':[to],'subject':subject,'text':text,'html':html or f'<p>{text}</p>'},timeout=20)
            return r.ok,'resend'
        except Exception: pass
    host=os.getenv('SMTP_HOST'); user=os.getenv('SMTP_USER'); pw=os.getenv('SMTP_PASS')
    if host and user and pw:
        try:
            msg=EmailMessage(); msg['From']=os.getenv('EMAIL_FROM',user); msg['To']=to; msg['Subject']=subject; msg.set_content(text)
            with smtplib.SMTP(host,int(os.getenv('SMTP_PORT','587'))) as s:
                s.starttls(context=ssl.create_default_context()); s.login(user,pw); s.send_message(msg)
            return True,'smtp'
        except Exception: pass
    return False,'simulated'

# ---------------- session ----------------
def init():
    defaults={'page':'Dashboard','logged_in':False,'profile':DEFAULT_PROFILE.copy(),'categories':INITIAL_CATEGORIES.copy(),'transactions':INITIAL_TRANSACTIONS.copy(),'goals':INITIAL_GOALS.copy(),'risk':INITIAL_RISK_PROFILE.copy(),'chat':[],'auth_screen':'select','forgot':{},'quick_add':False,'custom_plan':None}
    for k,v in defaults.items(): st.session_state.setdefault(k,v)
init()

def set_user(profile):
    st.session_state.profile={**DEFAULT_PROFILE,**profile,'isLoggedIn':True}; st.session_state.logged_in=True
    st.session_state.categories,st.session_state.transactions,st.session_state.goals,st.session_state.risk=load_workspace(st.session_state.profile['email'])
    save_workspace(st.session_state.profile['email'],st.session_state.categories,st.session_state.transactions,st.session_state.goals,st.session_state.risk,st.session_state.profile)
    st.session_state.page='Dashboard'

def persist():
    p=st.session_state.profile
    if p.get('email'): save_workspace(p['email'],st.session_state.categories,st.session_state.transactions,st.session_state.goals,st.session_state.risk,p)

def logout(): st.session_state.logged_in=False; st.session_state.profile=DEFAULT_PROFILE.copy(); st.session_state.page='Dashboard'; st.session_state.auth_screen='select'

# ---------------- styling ----------------
st.set_page_config(page_title='Finova — Intelligent Wealth & Stock Market OS',page_icon='assets/finova-logo.svg',layout='wide',initial_sidebar_state='expanded')
st.markdown('''<style>
[data-testid="stAppViewContainer"]{background:#0a0b0d;color:#e5e7eb}.stApp{background:#0a0b0d}.block-container{padding-top:1.2rem;max-width:1600px}
[data-testid="stSidebar"]{background:#101217;border-right:1px solid #24262d}.fin-card{background:linear-gradient(145deg,#12151a,#0d0f13);border:1px solid #252932;border-radius:16px;padding:18px;margin-bottom:14px;box-shadow:0 8px 30px rgba(0,0,0,.18)}
.fin-title{font-size:2rem;font-weight:800;color:#f4f4f5}.muted{color:#8b93a3}.gold{color:#f59e0b}.green{color:#10b981}.red{color:#ef4444}.metric{font-size:1.6rem;font-weight:800}.pill{display:inline-block;border:1px solid #3a3f49;border-radius:999px;padding:4px 10px;color:#cbd5e1;font-size:.78rem}
.stButton>button{border-radius:10px;border:1px solid #343944;background:#171a20;color:#e5e7eb}.stButton>button:hover{border-color:#f59e0b;color:#f59e0b}.stTextInput input,.stNumberInput input,.stSelectbox>div,.stTextArea textarea{background:#111419!important;color:#e5e7eb!important;border-color:#30343d!important;border-radius:10px!important}
[data-testid="stMetric"]{background:#111419;border:1px solid #252932;padding:12px;border-radius:14px}.small{font-size:.85rem}.section{margin-top:18px;margin-bottom:8px;font-size:1.15rem;font-weight:700}.navbtn button{width:100%;text-align:left}
</style>''',unsafe_allow_html=True)

# ---------------- auth ----------------
def auth_screen():
    st.markdown('<div style="text-align:center;margin-top:25px">',unsafe_allow_html=True)
    st.image('assets/finova-logo.svg',width=90); st.markdown('<div class="fin-title">FINOVA</div><div class="muted">Intelligent Wealth & Stock Market OS</div></div>',unsafe_allow_html=True)
    st.divider()
    mode=st.session_state.auth_screen
    if mode=='select':
        st.subheader('Welcome to Finova')
        c1,c2=st.columns(2)
        with c1:
            if st.button('🔐 Existing User',use_container_width=True): st.session_state.auth_screen='login'; st.rerun()
        with c2:
            if st.button('✨ New User',use_container_width=True): st.session_state.auth_screen='register'; st.rerun()
        if st.button('🔑 Forgot Password',use_container_width=True): st.session_state.auth_screen='forgot'; st.rerun()
    elif mode=='login':
        st.subheader('Sign in')
        method=st.radio('Login with',['Email','Phone'],horizontal=True)
        ident=st.text_input('Email' if method=='Email' else 'Phone')
        pw=st.text_input('Password',type='password')
        if st.button('Log In',type='primary',use_container_width=True):
            a=account(ident if method=='Email' else ident)
            if not a: st.error('Account not found. Please register first.')
            elif not verify_password(pw,a['password']): st.error('Incorrect password. Please verify your credentials and try again.')
            else: set_user(json.loads(a['profile'])); st.rerun()
        if st.button('← Back'): st.session_state.auth_screen='select'; st.rerun()
        if st.button('Forgot password?'): st.session_state.auth_screen='forgot'; st.rerun()
    elif mode=='register':
        st.subheader('Create your Finova account')
        with st.form('register'):
            c1,c2=st.columns(2)
            with c1:
                name=st.text_input('Full Name'); email=st.text_input('Email'); phone=st.text_input('Phone'); pw=st.text_input('Password',type='password'); cpw=st.text_input('Confirm Password',type='password'); age=st.number_input('Age',18,100,24); occupation=st.text_input('Occupation','Student / Engineer'); city=st.text_input('City','Bengaluru, Karnataka')
            with c2:
                income=st.number_input('Monthly Income',0.0,100000000.0,65000.0,step=1000.0); budget=st.number_input('Monthly Budget Cap',0.0,100000000.0,38000.0,step=1000.0); sip=st.number_input('Monthly SIP Target',0.0,100000000.0,18000.0,step=1000.0); currency=st.selectbox('Currency',list(CURRENCIES.keys())); risk=st.selectbox('Risk Tolerance',RISK_OPTIONS,index=1)
                st.caption('Expense breakdown'); r=st.number_input('Rent & Housing',0.0,1000000.0,18000.0); g=st.number_input('Groceries & Food',0.0,1000000.0,12000.0); u=st.number_input('Utilities & Bills',0.0,1000000.0,3500.0); t=st.number_input('Transport & Fuel',0.0,1000000.0,4500.0); e=st.number_input('Education',0.0,1000000.0,4000.0); ent=st.number_input('Entertainment',0.0,1000000.0,3500.0); med=st.number_input('Medical',0.0,1000000.0,3000.0); em=st.number_input('Emergency/Insurance',0.0,1000000.0,3500.0); misc=st.number_input('Miscellaneous',0.0,1000000.0,2000.0)
            agree=st.checkbox('I agree to the Finova terms and educational-use disclaimer',value=True)
            submitted=st.form_submit_button('Create Account',type='primary',use_container_width=True)
        if submitted:
            if not name or not email or '@' not in email or len(pw)<6: st.error('Enter valid details and a password of at least 6 characters.')
            elif pw!=cpw: st.error('Passwords do not match.')
            elif account(email): st.error('An account with this email already exists.')
            elif not agree: st.error('Please accept the terms to continue.')
            else:
                profile={**DEFAULT_PROFILE,'name':name,'email':email.lower().strip(),'phone':phone,'age':age,'occupation':occupation,'city':city,'monthlyIncome':income,'monthlyBudgetCap':budget,'monthlySipTarget':sip,'currency':currency,'riskTolerance':risk,'expenseBreakdown':{'rentAndHousing':r,'medicalsAndHealthcare':med,'groceriesAndFood':g,'utilitiesAndBills':u,'transportAndFuel':t,'educationAndLearning':e,'entertainmentAndLeisure':ent,'insuranceAndEmergency':em,'miscellaneous':misc}}
                save_account(profile,pw); set_user(profile); st.success('Account created successfully.'); st.rerun()
        if st.button('← Back'): st.session_state.auth_screen='select'; st.rerun()
    else: forgot_flow()

def forgot_flow():
    st.subheader('Reset your password')
    f=st.session_state.forgot; step=f.get('step',1)
    if step==1:
        email=st.text_input('Registered email',value=f.get('email',''))
        if st.button('Send Verification Code',type='primary'):
            a=account(email)
            if not a: st.error('No Finova account was found for this email.')
            else:
                now=datetime.utcnow(); code=f'{secrets.randbelow(900000)+100000}'; f.update({'step':2,'email':email.lower().strip(),'code_hash':hmac.new(os.getenv('OTP_SECRET_SALT','finova_secure_otp_salt_2026').encode(),f'{email.lower().strip()}:{code}'.encode(),hashlib.sha256).hexdigest(),'expires':(now+timedelta(minutes=10)).timestamp(),'attempts':0,'cooldown':(now+timedelta(seconds=60)).timestamp()}); st.session_state.forgot=f
                ok,provider=send_email(email,'Your Password Reset Verification Code - Finova',f'Your 6-digit Finova password reset code is: {code}\nIt expires in 10 minutes. Do not share this code.')
                if ok: st.success(f'Verification code sent to {email}.')
                elif provider=='simulated': st.warning('Email service is not configured. Configure RESEND_API_KEY or SMTP settings in .env to send real emails.')
                else: st.error('Unable to send email. Please check your email settings.')
                if not ok and os.getenv('SHOW_DEV_OTP','false').lower()=='true': st.code(code)
                st.rerun()
    elif step==2:
        remaining=max(0,int(f.get('expires',0)-datetime.utcnow().timestamp())); st.info(f'Code expires in {remaining//60}:{remaining%60:02d}')
        otp=st.text_input('6-digit verification code',max_chars=6)
        if st.button('Verify Code',type='primary'):
            f['attempts']=f.get('attempts',0)+1
            good=remaining>0 and f['attempts']<=5 and hmac.compare_digest(f.get('code_hash',''),hmac.new(os.getenv('OTP_SECRET_SALT','finova_secure_otp_salt_2026').encode(),f"{f['email']}:{otp.strip()}".encode(),hashlib.sha256).hexdigest())
            if good: f['step']=3; f['reset_token']=secrets.token_urlsafe(32); st.session_state.forgot=f; st.rerun()
            else: st.error('Invalid or expired verification code.')
        if st.button('Back'): st.session_state.forgot={}; st.session_state.auth_screen='select'; st.rerun()
    else:
        p1=st.text_input('New password',type='password'); p2=st.text_input('Confirm new password',type='password')
        if st.button('Reset Password',type='primary'):
            if len(p1)<6: st.error('Password must be at least 6 characters.')
            elif p1!=p2: st.error('Passwords do not match.')
            else:
                a=account(f['email']); prof=json.loads(a['profile']); save_account(prof,p1); st.session_state.forgot={}; st.session_state.auth_screen='login'; st.success('Password reset successfully.'); st.rerun()
        if st.button('Cancel'): st.session_state.forgot={}; st.session_state.auth_screen='select'; st.rerun()

# ---------------- common UI ----------------
def header(title,subtitle=''):
    c1,c2=st.columns([5,1])
    with c1: st.markdown(f'<div class="fin-title">{title}</div><div class="muted">{subtitle}</div>',unsafe_allow_html=True)
    with c2:
        p=st.session_state.profile
        st.markdown(f'<div style="text-align:right"><span class="pill">{p.get("riskTolerance","Moderate")}</span><br><span class="small muted">{p.get("name","Investor")}</span></div>',unsafe_allow_html=True)

def metric_row(items):
    cols=st.columns(len(items))
    for c,(label,val,delta) in zip(cols,items):
        with c: st.metric(label,val,delta)

def sidebar():
    p=st.session_state.profile
    with st.sidebar:
        st.image(p.get('appLogoUrl') or 'assets/finova-logo.svg',width=60)
        st.markdown('### FINOVA')
        st.caption('Intelligent Wealth & Stock Market OS')
        sections={
          'Overview':['Dashboard','Personal Finance','Transactions'],
          'Wealth':['Goals','Risk Assessment','AI Investment Planner','SIP Simulator','What-If Analysis','Analytics'],
          'Market & AI':['Stock Market','AI Co-Pilot'],
          'Security':['Authenticate / KYC','Settings']}
        for sec,pages in sections.items():
            st.caption(sec)
            for pg in pages:
                if st.button(('● ' if st.session_state.page==pg else '')+pg,key='nav_'+pg,use_container_width=True): st.session_state.page=pg; st.rerun()
        st.divider()
        st.caption(f'Logged in as {p.get("email")}')
        if st.button('🚪 Logout',use_container_width=True): logout(); st.rerun()

def stock_card(stock):
    pos=stock['changePercent']>=0
    st.markdown(f'''<div class="fin-card"><div style="display:flex;justify-content:space-between"><div><b>{stock['symbol']}</b><div class="muted small">{stock['name']}</div></div><div style="text-align:right"><b>{money(stock['priceINR'],'INR')}</b><div class="{'green' if pos else 'red'}">{'+' if pos else ''}{stock['changePercent']:.2f}%</div></div></div><div class="small muted">{stock['sector']} • {stock['exchange']} • P/E {stock.get('peRatio','—')} • {stock['marketCapINR']}</div></div>''',unsafe_allow_html=True)

# ---------------- pages ----------------
def dashboard():
    p=st.session_state.profile; cats=st.session_state.categories; tx=st.session_state.transactions; goals=st.session_state.goals; ms=monthly_stats(tx); hs=health_score(p,cats,goals)
    header(f'Good day, {p.get("name","Investor")} 👋','Your intelligent financial command center')
    metric_row([('Monthly Income',money(ms['income'] or p.get('monthlyIncome',0),p['currency']),None),('Expenses',money(ms['expenses'],p['currency']),None),('Investments',money(ms['investments'],p['currency']),None),('Net Savings',money(ms['netSavings'],p['currency']),pct(ms['savingsRate']))])
    c1,c2=st.columns([1,2])
    with c1:
        st.markdown('<div class="fin-card"><b>Financial Health</b></div>',unsafe_allow_html=True)
        st.progress(hs['score']/100); st.markdown(f'<div class="metric">{hs["score"]}/100 <span class="pill">Grade {hs["grade"]}</span></div><div class="muted">{hs["ratingText"]}</div>',unsafe_allow_html=True)
        st.write(pd.DataFrame({'Metric':list(hs['breakdown']),'Score':list(hs['breakdown'].values())}).set_index('Metric'))
    with c2:
        st.markdown('<div class="fin-card"><b>Budget vs Spending</b></div>',unsafe_allow_html=True)
        df=pd.DataFrame([{'Category':c['name'],'Allocated':c['allocated'],'Spent':c['spent']} for c in cats]); st.bar_chart(df.set_index('Category')[['Allocated','Spent']])
    c1,c2=st.columns(2)
    with c1:
        st.subheader('Top Spending Categories'); top=sorted(cats,key=lambda x:x['spent'],reverse=True)[:5]
        for c in top: st.write(f'**{c["name"]}** — {money(c["spent"],p["currency"])} / {money(c["allocated"],p["currency"])}')
    with c2:
        st.subheader('Active Goals')
        for g in [x for x in goals if not x.get('completed')][:3]: st.write(f'**{g["title"]}** — {money(g["currentAmount"],p["currency"])} / {money(g["targetAmount"],p["currency"])}'); st.progress(min(1,g['currentAmount']/max(1,g['targetAmount'])))
    st.subheader('Recent Transactions')
    st.dataframe(pd.DataFrame(tx[:5])[['date','title','type','category','amount','paymentMethod']],use_container_width=True,hide_index=True)
    st.subheader('Market Pulse')
    inds=MARKET['MAJOR_MARKET_INDICES']; metric_row([(i['name'],f"{i['value']:,.2f}",f"{i['changePercent']:+.2f}%") for i in inds[:4]])
    if st.button('Run AI Budget Audit'):
        result=ai_generate(f'Analyze income {ms["income"]}, expenses {ms["expenses"]}, categories {cats}', 'You are a prudent financial coach. Return JSON with healthScore, summary, highlights, actionableTips, riskAlert.',True)
        if not result:
            s=max(0,round((ms['income']-ms['expenses'])/max(1,ms['income'])*100)); result={'healthScore':min(100,75+s//2),'summary':f'Your monthly savings rate is {s}%.','highlights':[f'Top spending area is {top[0]["name"]}.','Review recurring costs.','Maintain a 3-6 month reserve.'],'actionableTips':['Automate a SIP from surplus.','Optimize discretionary spending 10-15%.','Keep emergency reserves liquid.'],'riskAlert':None}
        st.session_state.ai_audit=result
    if st.session_state.get('ai_audit'): st.json(st.session_state.ai_audit)

def personal_finance():
    p=st.session_state.profile; header('Personal Finance','Manage your income, budget, SIP target and expense architecture')
    with st.form('finance_form'):
        c1,c2,c3=st.columns(3)
        with c1: income=st.number_input('Monthly Income',0.0,value=float(p.get('monthlyIncome',65000))); budget=st.number_input('Budget Cap',0.0,value=float(p.get('monthlyBudgetCap',38000)))
        with c2: sip=st.number_input('Monthly SIP Target',0.0,value=float(p.get('monthlySipTarget',18000))); emergency=st.number_input('Emergency Fund (months)',0.0,24.0,float(p.get('emergencyFundMonths',6)))
        with c3: savings=st.number_input('Target Savings Rate %',0.0,100.0,float(p.get('targetSavingsRate',35))); risk=st.selectbox('Risk Tolerance',RISK_OPTIONS,index=RISK_OPTIONS.index(p.get('riskTolerance','Moderate')))
        submitted=st.form_submit_button('Save Financial Profile',type='primary')
    if submitted:
        p.update({'monthlyIncome':income,'monthlyBudgetCap':budget,'monthlySipTarget':sip,'emergencyFundMonths':emergency,'targetSavingsRate':savings,'riskTolerance':risk}); persist(); st.success('Financial profile updated.')
    st.subheader('Expense Breakdown Targets')
    eb=p.get('expenseBreakdown') or {}; labels=[('rentAndHousing','Rent & Housing'),('medicalsAndHealthcare','Medical & Healthcare'),('groceriesAndFood','Groceries & Food'),('utilitiesAndBills','Utilities & Bills'),('transportAndFuel','Transport & Fuel'),('educationAndLearning','Education & Learning'),('entertainmentAndLeisure','Entertainment & Leisure'),('insuranceAndEmergency','Insurance & Emergency'),('miscellaneous','Miscellaneous')]
    cols=st.columns(3)
    for i,(k,l) in enumerate(labels):
        with cols[i%3]: eb[k]=st.number_input(l,0.0,value=float(eb.get(k,0)),key='eb_'+k)
    p['expenseBreakdown']=eb
    if st.button('Save Expense Targets'): persist(); st.success('Targets saved.')
    total=sum(eb.values()); st.metric('Target monthly expenses',money(total,p['currency']),f'{(total/max(1,p["monthlyIncome"])*100):.1f}% of income')

def transactions():
    p=st.session_state.profile; header('Transactions','Track income, expenses and investments')
    with st.expander('➕ Add Transaction',expanded=False):
        with st.form('tx'):
            title=st.text_input('Title'); amount=st.number_input('Amount',0.0,100000000.0,0.0); typ=st.selectbox('Type',['expense','income','investment']); cat=st.selectbox('Category',CATEGORIES); method=st.selectbox('Payment Method',PAYMENT_METHODS); dt=st.date_input('Date',date.today()); notes=st.text_area('Notes'); rec=st.checkbox('Recurring')
            if st.form_submit_button('Add Transaction',type='primary'):
                st.session_state.transactions.insert(0,{'id':'tx_'+secrets.token_hex(5),'title':title or 'Transaction','amount':amount,'type':typ,'category':cat,'date':dt.isoformat(),'paymentMethod':method,'notes':notes,'tags':[],'isRecurring':rec}); persist(); st.rerun()
    df=pd.DataFrame(st.session_state.transactions); st.dataframe(df[['date','title','type','category','amount','paymentMethod','notes']],use_container_width=True,hide_index=True)
    ids=[t['id'] for t in st.session_state.transactions]; selected=st.selectbox('Delete a transaction', ['—']+ids,format_func=lambda x: next((t['title'] for t in st.session_state.transactions if t['id']==x),'—'))
    if selected!='—' and st.button('Delete Selected Transaction'): st.session_state.transactions=[t for t in st.session_state.transactions if t['id']!=selected]; persist(); st.rerun()
    st.subheader('Quick Natural-Language Entry')
    text=st.text_input('e.g. "spent ₹850 on dinner via UPI"')
    if st.button('Parse & Add') and text:
        parsed=ai_generate(f'Extract transaction from: {text}','Return JSON with title, amount, type, category, paymentMethod, notes.',True) or parse_expense_fallback(text)
        st.session_state.transactions.insert(0,{'id':'tx_'+secrets.token_hex(5),**parsed,'date':date.today().isoformat(),'tags':[]}); persist(); st.success('Transaction added.'); st.rerun()

def goals():
    p=st.session_state.profile; header('Financial Goals','Plan, fund and track your financial milestones')
    with st.expander('🎯 Add Goal'):
        with st.form('goal'):
            title=st.text_input('Goal name'); cat=st.selectbox('Category',GOAL_CATEGORIES); target=st.number_input('Target Amount',0.0); current=st.number_input('Current Amount',0.0); td=st.date_input('Target Date',date.today()+timedelta(days=365)); contrib=st.number_input('Monthly Contribution',0.0); priority=st.selectbox('Priority',['high','medium','low']); notes=st.text_area('Notes')
            if st.form_submit_button('Create Goal',type='primary'):
                st.session_state.goals.append({'id':'goal_'+secrets.token_hex(5),'title':title or 'New Goal','category':cat,'targetAmount':target,'currentAmount':current,'targetDate':td.isoformat(),'monthlyContribution':contrib,'priority':priority,'icon':'Target','notes':notes}); persist(); st.rerun()
    for g in st.session_state.goals:
        progress=min(100,100*g['currentAmount']/max(1,g['targetAmount'])); req=goal_monthly(g['targetAmount'],g['currentAmount'],g['targetDate'])
        st.markdown(f'<div class="fin-card"><b>{g["title"]}</b> <span class="pill">{g["priority"]}</span><br><span class="muted">{g["category"]} • target {fdate(g["targetDate"])}</span></div>',unsafe_allow_html=True)
        st.progress(progress/100); st.write(f'{money(g["currentAmount"],p["currency"])} / {money(g["targetAmount"],p["currency"])} — {progress:.1f}%'); st.caption(f'Recommended monthly contribution at 10% annual return: {money(req,p["currency"])}')
        c1,c2=st.columns(2); amount=c1.number_input('Add funds',0.0,key='fund_'+g['id']);
        if c2.button('Add',key='add_'+g['id']) and amount>0: g['currentAmount']+=amount; persist(); st.rerun()

def risk_assessment():
    p=st.session_state.profile; header('Risk Assessment','Understand your tolerance, horizon and recommended allocation')
    questions=[('q1_horizon','Investment horizon',4),('q2_reaction','Reaction to market fall',3),('q3_emergency','Emergency fund readiness',4),('q4_knowledge','Investment knowledge',3),('q5_volatility','Comfort with volatility',4),('q6_dependents','Financial capacity',4)]
    answers=st.session_state.risk.get('answers',{}); cols=st.columns(2)
    for i,(k,q,default) in enumerate(questions):
        with cols[i%2]: answers[k]=st.slider(q,1,5,int(answers.get(k,default)),key='risk_'+k)
    if st.button('Calculate Risk Profile',type='primary'):
        score=round(sum(answers.values())/30*100); cat='Conservative' if score<40 else 'Moderate Conservative' if score<55 else 'Moderate' if score<70 else 'Growth' if score<85 else 'Aggressive'
        r=dict(st.session_state.risk); r.update({'score':score,'category':cat,'answers':answers,'horizonScore':answers['q1_horizon']*20,'toleranceScore':answers['q2_reaction']*20,'financialBufferScore':answers['q3_emergency']*20,'lastUpdated':datetime.now().isoformat()}); st.session_state.risk=r; persist(); st.success(f'Risk profile: {cat} ({score}/100)')
    r=st.session_state.risk; st.metric('Risk Score',f"{r['score']}/100",r['category']); st.write(r.get('explanation','Long-term growth profile with diversified equity and defensive assets.'))
    if r.get('recommendedAllocations'): st.dataframe(pd.DataFrame(r['recommendedAllocations']),use_container_width=True,hide_index=True)

def planner():
    p=st.session_state.profile; header('AI Investment Planner','Generate a personalized educational asset allocation plan')
    ms=monthly_stats(st.session_state.transactions); surplus=max(0,ms['netSavings']); st.metric('Monthly investible surplus',money(surplus,p['currency']))
    if st.button('✨ Generate Custom AI Plan',type='primary'):
        plan=ai_generate(f'Create portfolio for profile {p}, risk {st.session_state.risk}, surplus {surplus}, goals {st.session_state.goals}','Return JSON with portfolioName, rationale, allocations, projected5YearCorpus, projected10YearCorpus, keyPrinciples.',True) or portfolio_fallback(p,st.session_state.risk,surplus); st.session_state.custom_plan=plan
    plan=st.session_state.custom_plan or portfolio_fallback(p,st.session_state.risk,surplus)
    st.markdown(f'### {plan["portfolioName"]}'); st.write(plan['rationale']); st.dataframe(pd.DataFrame(plan['allocations']),use_container_width=True,hide_index=True)
    metric_row([('5Y projection',money(plan['projected5YearCorpus'],p['currency']),None),('10Y projection',money(plan['projected10YearCorpus'],p['currency']),None)])
    for x in plan['keyPrinciples']: st.write('• '+x)

def simulator():
    p=st.session_state.profile; header('SIP Wealth Simulator','Visualize long-term compounding')
    c1,c2,c3=st.columns(3); monthly=c1.number_input('Monthly SIP',0.0,value=float(p.get('monthlySipTarget',18000))); rate=c2.number_input('Expected return %',0.0,40.0,12.0); years=c3.slider('Years',1,40,10)
    initial=st.number_input('Initial corpus',0.0,value=0.0); df=sip_projection(monthly,rate,years,initial); st.line_chart(df.set_index('Year')['Corpus']); st.dataframe(df.style.format({'Corpus':lambda x:money(x,p['currency']),'Invested':lambda x:money(x,p['currency']),'Returns':lambda x:money(x,p['currency'])}),use_container_width=True,hide_index=True)

def what_if():
    p=st.session_state.profile; header('What-If Analysis','Model salary growth, expense cuts and extra investing')
    c=st.columns(5); cut=c[0].slider('Expense cut %',0,50,10); extra=c[1].number_input('Extra monthly investment',0.0,1000000.0,5000.0); ret=c[2].number_input('Expected return %',0.0,30.0,12.0); inc=c[3].number_input('Salary increment %',0.0,50.0,8.0); yrs=c[4].slider('Horizon years',1,30,10)
    base=p.get('monthlyIncome',65000); expenses=monthly_stats(st.session_state.transactions)['expenses']; adjusted_exp=expenses*(1-cut/100); monthly=max(0,base*(1+inc/100)-adjusted_exp+extra); df=sip_projection(monthly,ret,yrs); st.metric('Projected monthly investible cash',money(monthly,p['currency'])); st.metric('Projected corpus',money(df.iloc[-1]['Corpus'],p['currency'])); st.line_chart(df.set_index('Year')['Corpus'])

def analytics():
    p=st.session_state.profile; header('Analytics','Deep-dive into spending, payment methods and trends'); cats=st.session_state.categories; tx=st.session_state.transactions; ms=monthly_stats(tx)
    c1,c2=st.columns(2)
    with c1:
        df=pd.DataFrame([{'Category':x['name'],'Spent':x['spent']} for x in cats]); st.plotly_chart(px.pie(df,names='Category',values='Spent',hole=.55),use_container_width=True)
    with c2:
        pm={};
        for t in tx:
            if t['type']=='expense': pm[t['paymentMethod']]=pm.get(t['paymentMethod'],0)+t['amount']
        d=pd.DataFrame({'Payment Method':list(pm),'Amount':list(pm.values())}); st.plotly_chart(px.bar(d,x='Payment Method',y='Amount'),use_container_width=True)
    st.subheader('Category budget utilization')
    rows=[]
    for c in cats: rows.append({'Category':c['name'],'Allocated':c['allocated'],'Spent':c['spent'],'Utilization %':round(c['spent']/max(1,c['allocated'])*100,1)})
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

def stock_market():
    p=st.session_state.profile; header('Stock Market','Market intelligence, watchlist and AI sentiment')
    inds=MARKET['MAJOR_MARKET_INDICES']; metric_row([(i['name'],f"{i['value']:,.2f}",f"{i['changePercent']:+.2f}%") for i in inds])
    cat=st.selectbox('Market category',['all','indian','global','indices','commodities']); search=st.text_input('Search stocks')
    stocks=MARKET['STOCKS_DATA']; filtered=[s for s in stocks if (cat=='all' or s['category']==cat) and (not search or search.lower() in (s['symbol']+' '+s['name']).lower())]
    st.subheader('Top Gainers'); gainers=sorted(stocks,key=lambda s:s['changePercent'],reverse=True)[:4]; cols=st.columns(4)
    for c,s in zip(cols,gainers):
        with c: stock_card(s)
    st.subheader('Stocks')
    for i in range(0,len(filtered),3):
        cols=st.columns(3)
        for c,s in zip(cols,filtered[i:i+3]):
            with c:
                stock_card(s)
                if st.button('View details',key='stock_'+s['id']): st.session_state.selected_stock=s
    if st.session_state.get('selected_stock'):
        s=st.session_state.selected_stock; st.divider(); st.subheader(f"{s['name']} ({s['symbol']})"); metric_row([('Price',money(s['priceINR'],'INR'),f"{s['changePercent']:+.2f}%"),('52W High',money(s['week52HighINR'],'INR'),None),('52W Low',money(s['week52LowINR'],'INR'),None),('AI Sentiment',s['aiSentiment'],f"{s['aiSentimentScore']}/100")]); period=st.selectbox('Chart period',['1D','1W','1M','1Y','5Y']); hist=s.get('history'+period,[]); st.line_chart(pd.DataFrame(hist).set_index('time')['price']); st.info(s['aiInsight']); st.markdown(f"[TradingView](https://www.tradingview.com/symbols/{s['symbol']}/) · [Google Finance](https://www.google.com/finance/quote/{s['symbol']}:{s['exchange']})")

def ai_copilot():
    p=st.session_state.profile; header('AI Co-Pilot','Ask Finova about budgets, goals, investing and market concepts')
    model=st.selectbox('AI Model',['gemini-3.7','chatgpt-4o']); prompts=['Analyze my spending','How can I reach my goals faster?','Build an optimal SIP allocation','Explain SIP compounding']
    cols=st.columns(4)
    for c,q in zip(cols,prompts):
        if c.button(q): st.session_state.pending_prompt=q
    for m in st.session_state.chat: st.chat_message(m['role']).write(m['content'])
    text=st.chat_input('Ask Finova anything...') or st.session_state.pop('pending_prompt',None)
    if text:
        st.session_state.chat.append({'role':'user','content':text}); ms=monthly_stats(st.session_state.transactions); context=f'User {p["name"]}, income {ms["income"]}, expenses {ms["expenses"]}, risk {st.session_state.risk["category"]}, goals {st.session_state.goals}'
        system='You are Finova AI Financial Co-Pilot. Give structured educational personal finance guidance, use the user context, explain calculations, and avoid claiming guaranteed returns.'
        reply=ai_generate(context+'\nQuestion: '+text,system,False) or f'Based on your current snapshot, your monthly income is {money(ms["income"],p["currency"])} and expenses are {money(ms["expenses"],p["currency"])}. Your estimated monthly surplus is {money(ms["netSavings"],p["currency"])}. Consider strengthening your emergency reserve and automating a diversified SIP.'
        st.session_state.chat.append({'role':'assistant','content':reply}); st.rerun()
    if st.button('Clear Chat'): st.session_state.chat=[]; st.rerun()

def kyc():
    p=st.session_state.profile; header('Authenticate / KYC','Identity verification workspace')
    if p.get('kycStatus')=='verified': st.success(f"KYC verified — {p['kycData']['kycId']}")
    step=st.number_input('Step',1,5,int(st.session_state.get('kyc_step',1)),1); st.session_state.kyc_step=step
    if step==1:
        doc=st.selectbox('Document Type',['Aadhaar Card','PAN Card','Passport','Driving License','Voter ID']); num=st.text_input('Document Number'); name=st.text_input('Legal Name',p.get('name','')); dob=st.date_input('Date of Birth',date(2001,5,14)); addr=st.text_area('Address',p.get('city',''))
        if st.button('Continue'): st.session_state.kyc_doc={'documentType':doc,'documentNumber':num,'fullName':name,'dateOfBirth':dob.isoformat(),'address':addr}; st.session_state.kyc_step=2; st.rerun()
    elif step==2:
        front=st.file_uploader('Upload ID / document',type=['png','jpg','jpeg','pdf']); selfie=st.file_uploader('Upload selfie',type=['png','jpg','jpeg']); st.caption('Streamlit cannot access the browser camera in the same way as the React implementation; selfie upload is supported.')
        if front: st.session_state.kyc_front=front.getvalue()
        if selfie: st.session_state.kyc_selfie=selfie.getvalue()
        if st.button('Continue'): st.session_state.kyc_step=3; st.rerun()
    elif step==3:
        st.subheader('Liveness / selfie review'); st.info('For a production deployment, connect a dedicated KYC/face-liveness provider here. The original demo used browser-side capture and a progress simulation.'); ok=st.checkbox('I confirm this selfie belongs to me')
        if st.button('Continue') and ok: st.session_state.kyc_step=4; st.rerun()
    elif step==4:
        phone=st.text_input('Mobile number',p.get('phone','')); email=st.text_input('Email address',p.get('email','')); st.info('Verification codes can be connected to SMS/email providers. Email OTP uses the same SMTP/Resend configuration as password reset.')
        if st.button('Send email OTP'):
            code=f'{secrets.randbelow(900000)+100000}'; st.session_state.kyc_email_otp=hashlib.sha256(code.encode()).hexdigest(); st.session_state.kyc_email=code; ok,prov=send_email(email,'Finova KYC Verification Code',f'Your Finova KYC verification code is {code}.'); st.success('OTP sent.') if ok else st.warning('Email provider not configured.')
        eo=st.text_input('Email OTP'); mo=st.text_input('Mobile OTP (demo/provider hook)')
        if st.button('Continue'):
            ev=bool(eo and hashlib.sha256(eo.encode()).hexdigest()==st.session_state.get('kyc_email_otp'))
            if ev or os.getenv('ALLOW_DEMO_KYC','true').lower()=='true': st.session_state.kyc_verified={'email':email,'phone':phone}; st.session_state.kyc_step=5; st.rerun()
            else: st.error('Verify email OTP first.')
    else:
        d=st.session_state.get('kyc_doc',{}); kd={'documentType':d.get('documentType','PAN Card'),'documentNumber':d.get('documentNumber',''),'fullName':d.get('fullName',p['name']),'dateOfBirth':d.get('dateOfBirth',''),'address':d.get('address',''),'selfieUrl':'uploaded','mobileNumber':st.session_state.get('kyc_verified',{}).get('phone',p.get('phone','')),'mobileVerified':True,'emailAddress':st.session_state.get('kyc_verified',{}).get('email',p.get('email','')),'emailVerified':True,'kycId':f'FIN-KYC-2026-{secrets.randbelow(900000)+100000}','verifiedAt':datetime.now().isoformat()}; p.update({'isVerified':True,'kycStatus':'verified','kycData':kd}); persist(); st.success('Authentication completed successfully.'); st.json(kd); st.session_state.kyc_step=1

def settings():
    p=st.session_state.profile; header('Settings','Profile, appearance and data controls')
    with st.form('settings'):
        name=st.text_input('Name',p['name']); occ=st.text_input('Occupation',p.get('occupation','')); city=st.text_input('City',p.get('city','')); phone=st.text_input('Phone',p.get('phone','')); currency=st.selectbox('Currency',list(CURRENCIES.keys()),index=list(CURRENCIES.keys()).index(p.get('currency','INR'))); logo=st.text_input('App logo URL/path',p.get('appLogoUrl','assets/finova-logo.svg')); save=st.form_submit_button('Save Settings',type='primary')
    if save: p.update({'name':name,'occupation':occ,'city':city,'phone':phone,'currency':currency,'appLogoUrl':logo}); persist(); st.success('Settings saved.')
    st.subheader('Data controls')
    if st.button('Reset workspace to Finova demo data'): st.session_state.categories=json.loads(json.dumps(INITIAL_CATEGORIES)); st.session_state.transactions=json.loads(json.dumps(INITIAL_TRANSACTIONS)); st.session_state.goals=json.loads(json.dumps(INITIAL_GOALS)); st.session_state.risk=json.loads(json.dumps(INITIAL_RISK_PROFILE)); persist(); st.success('Workspace reset.')
    st.download_button('Export workspace JSON',json.dumps({'profile':p,'categories':st.session_state.categories,'transactions':st.session_state.transactions,'goals':st.session_state.goals,'risk':st.session_state.risk},indent=2),file_name='finova_workspace.json',mime='application/json')

# ---------------- quick add modal replacement ----------------
def quick_add():
    if not st.session_state.get('quick_add'): return
    with st.sidebar:
        st.markdown('### ⚡ Quick Add')
        q=st.text_input('Describe a transaction')
        if st.button('Parse & Add',key='qa_add') and q:
            parsed=ai_generate(f'Extract transaction from {q}','Return JSON with title, amount, type, category, paymentMethod, notes.',True) or parse_expense_fallback(q)
            st.session_state.transactions.insert(0,{'id':'tx_'+secrets.token_hex(5),**parsed,'date':date.today().isoformat(),'tags':[]}); persist(); st.session_state.quick_add=False; st.rerun()
        if st.button('Close',key='qa_close'): st.session_state.quick_add=False; st.rerun()

# ---------------- app ----------------
if not st.session_state.logged_in:
    auth_screen()
else:
    sidebar();
    if st.button('⚡ Quick Add',key='global_quick'): st.session_state.quick_add=True
    quick_add()
    page=st.session_state.page
    {'Dashboard':dashboard,'Personal Finance':personal_finance,'Transactions':transactions,'Goals':goals,'Risk Assessment':risk_assessment,'AI Investment Planner':planner,'SIP Simulator':simulator,'What-If Analysis':what_if,'Analytics':analytics,'Stock Market':stock_market,'AI Co-Pilot':ai_copilot,'Authenticate / KYC':kyc,'Settings':settings}.get(page,dashboard)()

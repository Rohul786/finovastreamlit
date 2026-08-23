import os, json, uuid, smtplib, ssl
from datetime import date, datetime
from email.mime.text import MIMEText
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from dotenv import load_dotenv
from data.defaults import PROFILE,CATEGORIES,TRANSACTIONS,GOALS,STOCKS
from utils.calculations import sip_projection, required_monthly, health_score

load_dotenv()
st.set_page_config(page_title='Finova — Intelligent Wealth & Stock Market OS', page_icon='assets/finova-logo.svg', layout='wide', initial_sidebar_state='expanded')

DATA_FILE='finova_data.json'

def load_db():
    if os.path.exists(DATA_FILE):
        try:
            return json.load(open(DATA_FILE,'r',encoding='utf-8'))
        except Exception: pass
    return {'accounts':{},'workspaces':{}}

def save_db(db): json.dump(db,open(DATA_FILE,'w',encoding='utf-8'),indent=2)

def money(x):
    return f"₹{x:,.0f}"

def inject_css():
    st.markdown('''<style>
    .stApp{background:#0a0b0d;color:#e5e7eb}.block-container{padding-top:1.1rem;max-width:1550px}
    [data-testid="stSidebar"]{background:#101216;border-right:1px solid #25272d}.stButton>button{border-radius:9px;border:1px solid #30333a;background:#17191e;color:#eee}
    .stButton>button:hover{border-color:#f59e0b;color:#f59e0b}.fin-card{background:#111318;border:1px solid #262932;border-radius:16px;padding:18px;height:100%;box-shadow:0 8px 28px rgba(0,0,0,.18)}
    .gold{color:#f59e0b}.muted{color:#8b919d}.big{font-size:28px;font-weight:750}.tiny{font-size:12px;color:#8b919d}.pill{display:inline-block;padding:4px 9px;border-radius:99px;background:#1c1f25;font-size:12px}.ok{color:#34d399}.bad{color:#fb7185}.warn{color:#fbbf24}
    div[data-testid="stMetric"]{background:#111318;border:1px solid #262932;padding:14px;border-radius:14px}.stTabs [data-baseweb="tab-list"]{gap:8px}.stTabs [data-baseweb="tab"]{background:#121419;border-radius:8px;padding:8px 16px}
    </style>''',unsafe_allow_html=True)

def card(title,value,sub=''):
    st.markdown(f'<div class="fin-card"><div class="muted">{title}</div><div class="big">{value}</div><div class="tiny">{sub}</div></div>',unsafe_allow_html=True)

def reset_workspace():
    st.session_state.profile=PROFILE.copy(); st.session_state.categories=[{'name':n,'allocated':a,'spent':s} for n,a,s in CATEGORIES]; st.session_state.transactions=[{'id':str(uuid.uuid4()),'title':t,'amount':a,'type':ty,'category':c,'date':d,'payment':p} for t,a,ty,c,d,p in TRANSACTIONS]; st.session_state.goals=[{'id':str(uuid.uuid4()),'title':t,'category':c,'target':ta,'current':ca,'date':d,'monthly':m,'priority':pr} for t,c,ta,ca,d,m,pr in GOALS]; st.session_state.chat=[]

def load_workspace(email):
    db=load_db(); ws=db.get('workspaces',{}).get(email)
    if ws:
        st.session_state.profile=ws.get('profile',PROFILE.copy()); st.session_state.categories=ws.get('categories',[]); st.session_state.transactions=ws.get('transactions',[]); st.session_state.goals=ws.get('goals',[])
    else: reset_workspace(); st.session_state.profile.update({'email':email,'is_logged_in':True})

def persist():
    p=st.session_state.get('profile',{}); email=p.get('email')
    if not email:return
    db=load_db(); db.setdefault('workspaces',{})[email]={'profile':p,'categories':st.session_state.categories,'transactions':st.session_state.transactions,'goals':st.session_state.goals}; save_db(db)

def send_email_otp(email,otp):
    resend=os.getenv('RESEND_API_KEY') or os.getenv('EMAIL_API_KEY')
    if resend:
        try:
            r=requests.post('https://api.resend.com/emails',headers={'Authorization':f'Bearer {resend}','Content-Type':'application/json'},json={'from':os.getenv('EMAIL_FROM','Finova Security <onboarding@resend.dev>'),'to':[email],'subject':'Your Finova verification code','html':f'<h2>Finova verification</h2><p>Your code is <b>{otp}</b>. It expires soon.</p>'},timeout=15); return r.ok
        except Exception:return False
    host=os.getenv('SMTP_HOST'); user=os.getenv('SMTP_USER'); pw=os.getenv('SMTP_PASS'); port=int(os.getenv('SMTP_PORT','587'))
    if host and user and pw:
        try:
            msg=MIMEText(f'Your Finova verification code is {otp}.'); msg['Subject']='Your Finova verification code'; msg['From']=os.getenv('EMAIL_FROM',user); msg['To']=email
            with smtplib.SMTP(host,port) as s: s.starttls(context=ssl.create_default_context()); s.login(user,pw); s.send_message(msg)
            return True
        except Exception:return False
    return False

def ai_answer(prompt):
    key=os.getenv('GEMINI_API_KEY')
    if not key:return 'AI is in demo mode. Add GEMINI_API_KEY to your .env/Streamlit secrets for live Gemini responses.\n\nBased on your Finova workspace, focus on keeping essential expenses within budget and maintaining your planned SIP contributions.'
    try:
        url=f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}'
        body={'contents':[{'parts':[{'text':f'You are Finova financial co-pilot. Give educational, non-personalized financial guidance. User context: income {st.session_state.profile.get("monthly_income",0)}, risk {st.session_state.profile.get("risk","Moderate")}. Question: {prompt}'}]}]}
        r=requests.post(url,json=body,timeout=30); data=r.json(); return data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:return f'AI service unavailable: {e}'

def auth_page():
    st.markdown('<div style="text-align:center;margin-top:4vh"><h1>Finova</h1><p class="muted">Intelligent Wealth & Stock Market OS</p></div>',unsafe_allow_html=True)
    left,mid,right=st.columns([1,1.25,1])
    with mid:
        tab=st.tabs(['Sign In','Create Account','Forgot Password'])
        db=load_db()
        with tab[0]:
            email=st.text_input('Email',key='login_email'); pw=st.text_input('Password',type='password',key='login_pw')
            if st.button('Sign In',use_container_width=True):
                acc=db.get('accounts',{}).get(email.lower())
                if acc and acc['password']==pw: load_workspace(email.lower()); st.rerun()
                elif not acc: st.error('Account not found. Create an account first.')
                else: st.error('Incorrect password.')
        with tab[1]:
            name=st.text_input('Full name'); email2=st.text_input('Email',key='signup_email'); phone=st.text_input('Phone'); p1=st.text_input('Password',type='password',key='p1'); p2=st.text_input('Confirm password',type='password',key='p2')
            if st.button('Create Account',use_container_width=True):
                if not email2 or p1!=p2: st.error('Enter a valid email and matching passwords.')
                elif email2.lower() in db.get('accounts',{}): st.error('An account with this email already exists.')
                else:
                    otp=str(np.random.randint(100000,999999)); st.session_state.pending_signup={'name':name,'email':email2.lower(),'phone':phone,'password':p1,'otp':otp}; sent=send_email_otp(email2,otp)
                    st.session_state.signup_sent=True; st.success('Verification code sent to your email.' if sent else f'Demo mode: verification code is {otp}. Configure email settings for real delivery.')
            if st.session_state.get('signup_sent'):
                code=st.text_input('Email verification code',key='signup_code')
                if st.button('Verify & Enter Finova'):
                    ps=st.session_state.get('pending_signup',{})
                    if code==ps.get('otp'):
                        db=load_db(); db.setdefault('accounts',{})[ps['email']]={'name':ps['name'],'email':ps['email'],'phone':ps['phone'],'password':ps['password']}; save_db(db); load_workspace(ps['email']); st.session_state.profile.update({'name':ps['name'],'phone':ps['phone'],'is_logged_in':True}); persist(); st.rerun()
                    else: st.error('Invalid verification code.')
        with tab[2]:
            fe=st.text_input('Account email',key='forgot_email')
            if st.button('Send Reset Code',use_container_width=True):
                acc=db.get('accounts',{}).get(fe.lower())
                if not acc: st.error('No account exists for that email.')
                else:
                    otp=str(np.random.randint(100000,999999)); st.session_state.reset={'email':fe.lower(),'otp':otp}; sent=send_email_otp(fe,otp); st.success('Reset code sent to your email.' if sent else f'Demo mode: reset code is {otp}.')
            if st.session_state.get('reset'):
                rc=st.text_input('Reset code'); npw=st.text_input('New password',type='password')
                if st.button('Reset Password'):
                    rs=st.session_state.reset
                    if rc==rs['otp'] and npw:
                        db=load_db(); db['accounts'][rs['email']]['password']=npw; save_db(db); st.success('Password reset successfully. You can now sign in.')
                    else: st.error('Invalid code or password.')

def sidebar():
    with st.sidebar:
        st.markdown('<h2 class="gold">◈ FINOVA</h2><div class="muted">Intelligent Wealth OS</div>',unsafe_allow_html=True); st.divider()
        p=st.session_state.profile; st.markdown(f'**{p.get("name","Investor")}**  \n<small>{p.get("email","")}</small>',unsafe_allow_html=True)
        items=[('⌂','Dashboard','dashboard'),('◉','Personal Finance','personal'),('↔','Transactions','transactions'),('◎','Goals','goals'),('◌','Risk Assessment','risk'),('✦','AI Investment Planner','planner'),('▣','Simulator','simulator'),('◇','What-If','whatif'),('◫','Analytics','analytics'),('✧','AI Co-Pilot','copilot'),('✓','KYC & Authenticate','authenticate'),('⚙','Settings','settings')]
        current=st.session_state.page
        for icon,label,key in items:
            if st.button(f'{icon}  {label}',key='nav_'+key,use_container_width=True): st.session_state.page=key; st.rerun()
        st.divider()
        if st.button('＋ Quick Add',use_container_width=True): st.session_state.quick=True
        if st.button('Sign Out',use_container_width=True): st.session_state.profile['is_logged_in']=False; st.session_state.page='dashboard'; persist(); st.rerun()

def topbar():
    p=st.session_state.profile; a,b,c=st.columns([6,1.5,1.5]);
    with a: st.markdown(f'### {p.get("name","Investor")} <span class="muted">/ Finova</span>',unsafe_allow_html=True)
    with b: st.selectbox('Currency',['INR','USD','EUR','GBP'],index=['INR','USD','EUR','GBP'].index(p.get('currency','INR')),key='currency')
    with c: st.markdown('<div style="padding-top:26px;text-align:right" class="pill">● Secure</div>',unsafe_allow_html=True)

def dashboard():
    p=st.session_state.profile; tx=st.session_state.transactions; inc=sum(x['amount'] for x in tx if x['type']=='income'); exp=sum(x['amount'] for x in tx if x['type']=='expense'); inv=sum(x['amount'] for x in tx if x['type']=='investment'); net=inc-exp-inv
    st.title('Dashboard'); st.caption('Your financial command center')
    cols=st.columns(5); vals=[('Monthly Income',inc,'Primary inflow'),('Expenses',exp,'This month'),('Investments',inv,'SIP + investments'),('Net Savings',net,'After expenses & investments'),('Savings Rate',f'{max(0,net/inc*100):.1f}%' if inc else '0%','Target 35%')]
    for c,(t,v,s) in zip(cols,vals): c.metric(t, money(v) if isinstance(v,(int,float)) else v,s)
    st.write('')
    l,r=st.columns([1.5,1])
    with l:
        st.subheader('Cashflow & Spending'); df=pd.DataFrame(tx); df['date']=pd.to_datetime(df['date']); df['Signed']=df.apply(lambda x:x['amount'] if x['type']=='income' else -x['amount'],axis=1); daily=df.groupby('date',as_index=False)['Signed'].sum(); fig=px.area(daily,x='date',y='Signed',template='plotly_dark'); fig.update_layout(height=300,margin=dict(l=0,r=0,t=10,b=0)); st.plotly_chart(fig,use_container_width=True)
    with r:
        score,grade,text=health_score(inc,exp,st.session_state.goals,st.session_state.categories); st.subheader('Financial Health'); st.metric('Health Score',f'{score}/100',grade); st.progress(score/100); st.caption(text); st.write('**Top priorities**'); st.write('• Keep rent and essential bills within plan\n• Maintain your monthly SIP target\n• Build the emergency cushion')
    st.subheader('Recent Transactions'); st.dataframe(pd.DataFrame(tx)[['title','amount','type','category','date','payment']].tail(8).iloc[::-1],use_container_width=True,hide_index=True)

def personal():
    st.title('Personal Finance'); p=st.session_state.profile
    a,b=st.columns(2)
    with a:
        st.subheader('Monthly Plan'); income=st.number_input('Monthly income',value=float(p['monthly_income']),step=1000.0); budget=st.number_input('Budget cap',value=float(p['monthly_budget']),step=1000.0); sip=st.number_input('Monthly SIP target',value=float(p['monthly_sip']),step=500.0); save=st.slider('Target savings rate',0,80,int(p['savings_rate']))
        if st.button('Save Finance Profile'): p.update({'monthly_income':income,'monthly_budget':budget,'monthly_sip':sip,'savings_rate':save}); persist(); st.success('Saved.')
    with b:
        st.subheader('Budget Allocation'); cats=st.session_state.categories
        for c in cats:
            val=st.number_input(c['name'],value=float(c['allocated']),step=500.0,key='alloc_'+c['name']); c['allocated']=val
        if st.button('Save Budgets'): persist(); st.success('Budgets updated.')

def transactions():
    st.title('Transactions'); df=pd.DataFrame(st.session_state.transactions)
    with st.expander('＋ Add Transaction',expanded=False):
        t=st.text_input('Title'); amount=st.number_input('Amount',min_value=0.0,step=100.0); typ=st.selectbox('Type',['income','expense','investment']); cat=st.selectbox('Category',[c['name'] for c in st.session_state.categories]+['Salary','Freelance']); dt=st.date_input('Date',date.today()); pm=st.selectbox('Payment Method',['UPI','Credit Card','Debit Card','Net Banking','PayPal','Cash','Crypto'])
        if st.button('Add'): st.session_state.transactions.append({'id':str(uuid.uuid4()),'title':t,'amount':amount,'type':typ,'category':cat,'date':dt.isoformat(),'payment':pm}); persist(); st.rerun()
    q=st.text_input('Search'); show=df[df['title'].str.contains(q,case=False,na=False)] if q else df; st.dataframe(show[['title','amount','type','category','date','payment']],use_container_width=True,hide_index=True)
    if st.button('Delete last transaction') and st.session_state.transactions: st.session_state.transactions.pop(); persist(); st.rerun()

def goals():
    st.title('Goals'); st.caption('Track progress toward the life you are building.')
    cols=st.columns(2)
    for i,g in enumerate(st.session_state.goals):
        with cols[i%2]:
            pct=min(1,g['current']/g['target']) if g['target'] else 0; st.markdown(f'<div class="fin-card"><b>{g["title"]}</b><div class="tiny">{g["category"]} · {g["priority"].title()} priority</div><h3>{money(g["current"])} <span class="muted">/ {money(g["target"] )}</span></h3></div>',unsafe_allow_html=True); st.progress(pct); st.caption(f'{pct*100:.0f}% complete · Target {g["date"]} · Monthly contribution {money(g["monthly"])}')
            add=st.number_input('Add funds',min_value=0.0,step=1000.0,key='goaladd'+g['id']);
            if st.button('Add to goal',key='goalbtn'+g['id']) and add>0: g['current']+=add; persist(); st.rerun()
    with st.expander('Create new goal'):
        title=st.text_input('Goal title'); target=st.number_input('Target amount',min_value=0.0,step=1000.0); current=st.number_input('Current amount',min_value=0.0,step=1000.0); d=st.date_input('Target date'); monthly=st.number_input('Monthly contribution',min_value=0.0,step=500.0)
        if st.button('Create goal'): st.session_state.goals.append({'id':str(uuid.uuid4()),'title':title,'category':'Custom','target':target,'current':current,'date':d.isoformat(),'monthly':monthly,'priority':'medium'}); persist(); st.rerun()

def risk():
    st.title('Risk Assessment'); st.caption('A simple educational risk-profile questionnaire.')
    horizon=st.slider('Investment horizon',1,20,7); decline=st.slider('If portfolio falls 25%, what do you do?',1,5,3); buffer=st.slider('Emergency fund strength',1,5,4); knowledge=st.slider('Investment experience',1,5,3)
    score=round((horizon/20*35)+(decline/5*25)+(buffer/5*20)+(knowledge/5*20)); cat='Conservative' if score<35 else 'Moderate Conservative' if score<50 else 'Moderate' if score<70 else 'Growth' if score<85 else 'Aggressive'
    st.metric('Risk Score',f'{score}/100',cat); st.progress(score/100)
    alloc={'Conservative':[('Debt',60),('Equity',25),('Gold',15)],'Moderate':[('Debt',35),('Equity',50),('Gold',15)],'Growth':[('Debt',20),('Equity',65),('Gold',15)],'Aggressive':[('Debt',10),('Equity',80),('Gold',10)]}.get(cat,[('Debt',45),('Equity',40),('Gold',15)])
    fig=px.pie(pd.DataFrame(alloc,columns=['Asset','Percent']),values='Percent',names='Asset',hole=.55,template='plotly_dark'); fig.update_layout(height=330); st.plotly_chart(fig,use_container_width=True); st.session_state.profile['risk']=cat

def planner():
    st.title('AI Investment Planner'); st.caption('Plan SIPs using compound growth projections.')
    a,b,c,d=st.columns(4); monthly=a.number_input('Monthly SIP',500.0,500000.0,float(st.session_state.profile['monthly_sip']),500.0); rate=b.number_input('Expected return %',0.0,30.0,12.0); years=c.slider('Years',1,30,10); step=d.number_input('Annual step-up %',0.0,30.0,5.0)
    rows=sip_projection(monthly,rate,years,step); df=pd.DataFrame(rows); final=df.iloc[-1];
    x,y,z=st.columns(3); x.metric('Total Invested',money(final['Invested'])); y.metric('Projected Corpus',money(final['Corpus'])); z.metric('Wealth Gained',money(final['Wealth Gained']))
    fig=go.Figure(); fig.add_trace(go.Scatter(x=df.Year,y=df.Invested,name='Invested')); fig.add_trace(go.Scatter(x=df.Year,y=df.Corpus,name='Corpus')); fig.update_layout(template='plotly_dark',height=380); st.plotly_chart(fig,use_container_width=True); st.dataframe(df,use_container_width=True,hide_index=True)

def simulator():
    st.title('SIP Simulator'); planner()

def whatif():
    st.title('What-If Analysis'); p=st.session_state.profile; income=p['monthly_income']; tx=st.session_state.transactions; exp=sum(x['amount'] for x in tx if x['type']=='expense');
    cut=st.slider('Reduce expenses by',0,50,10); extra=st.number_input('Extra monthly investment',0.0,200000.0,5000.0,500.0); ret=st.slider('Expected return',1.0,20.0,12.0); years=st.slider('Horizon',1,25,10)
    base=sip_projection(p['monthly_sip'],ret,years)[-1]['Corpus']; scenario=sip_projection(p['monthly_sip']+extra,ret,years)[-1]['Corpus']; monthly_saved=exp*cut/100; st.metric('Monthly cash freed',money(monthly_saved)); st.metric('Additional projected wealth',money(scenario-base)); st.info('This is a scenario calculator, not a guarantee of investment returns.')

def analytics():
    st.title('Analytics'); tx=pd.DataFrame(st.session_state.transactions); exp=tx[tx.type=='expense'].groupby('category',as_index=False).amount.sum().sort_values('amount',ascending=False); a,b=st.columns(2)
    with a:
        fig=px.bar(exp,x='amount',y='category',orientation='h',template='plotly_dark',title='Expense by category'); fig.update_layout(height=430); st.plotly_chart(fig,use_container_width=True)
    with b:
        typ=tx.groupby('type',as_index=False).amount.sum(); fig=px.pie(typ,values='amount',names='type',hole=.55,template='plotly_dark',title='Cash allocation'); fig.update_layout(height=430); st.plotly_chart(fig,use_container_width=True)
    st.subheader('Budget vs Spent'); cdf=pd.DataFrame(st.session_state.categories); cdf['Variance']=cdf.allocated-cdf.spent; st.dataframe(cdf,use_container_width=True,hide_index=True)

def stocks():
    st.title('Stock Market'); st.caption('Finova market workspace with the supplied demo market dataset.')
    s=pd.DataFrame(STOCKS,columns=['Symbol','Name','Exchange','Price INR','Change %','Sector','AI Sentiment']); s['Price']=s['Price INR'].map(money); st.dataframe(s[['Symbol','Name','Exchange','Price','Change %','Sector','AI Sentiment']],use_container_width=True,hide_index=True)
    pick=st.selectbox('Select stock',s.Symbol); row=s[s.Symbol==pick].iloc[0]; x,y,z=st.columns(3); x.metric(row['Name'],money(row['Price INR']),f"{row['Change %']}%"); y.metric('Sector',row['Sector']); z.metric('AI Sentiment',row['AI Sentiment']);
    prices=np.cumsum(np.random.default_rng(abs(hash(pick))%2**32).normal(0,1,90))+row['Price INR']; hist=pd.DataFrame({'Day':range(90),'Price':prices}); fig=px.line(hist,x='Day',y='Price',template='plotly_dark',title=f'{pick} — 90D demo chart'); st.plotly_chart(fig,use_container_width=True)

def copilot():
    st.title('AI Co-Pilot'); st.caption('Ask about budgeting, goals, SIPs, or the market.')
    for m in st.session_state.chat: st.chat_message(m['role']).write(m['content'])
    q=st.chat_input('Ask Finova AI...')
    if q:
        st.session_state.chat.append({'role':'user','content':q}); ans=ai_answer(q); st.session_state.chat.append({'role':'assistant','content':ans}); st.rerun()

def authenticate():
    st.title('KYC & Authenticate'); p=st.session_state.profile
    st.info('Demo KYC workflow. Connect your regulated KYC provider before using this in production.')
    doc=st.selectbox('Document',['Aadhaar Card','PAN Card','Passport','Driving License','Voter ID']); num=st.text_input('Document number'); full=st.text_input('Full name',value=p.get('name','')); dob=st.date_input('Date of birth',value=date(2002,1,1)); phone=st.text_input('Mobile number',value=p.get('phone','')); email=st.text_input('Email',value=p.get('email',''))
    if st.button('Submit KYC'): p.update({'verified':True,'kyc_status':'verified'}); persist(); st.success('KYC marked as verified in this demo workspace.')

def settings():
    st.title('Settings'); p=st.session_state.profile
    name=st.text_input('Name',p.get('name','')); occ=st.text_input('Occupation',p.get('occupation','')); city=st.text_input('City',p.get('city','')); age=st.number_input('Age',18,100,int(p.get('age',24))); currency=st.selectbox('Currency',['INR','USD','EUR','GBP'],index=['INR','USD','EUR','GBP'].index(p.get('currency','INR')))
    if st.button('Save Settings'): p.update({'name':name,'occupation':occ,'city':city,'age':age,'currency':currency}); persist(); st.success('Settings saved.')
    if st.button('Reset to Demo Data'): reset_workspace(); st.session_state.profile.update({'email':p.get('email',''),'is_logged_in':True,'name':p.get('name','Investor')}); persist(); st.success('Demo data restored.')

def quick_add():
    with st.form('quickadd'):
        st.subheader('Quick Add'); title=st.text_input('Title'); amount=st.number_input('Amount',0.0,10000000.0,1000.0); typ=st.selectbox('Type',['expense','income','investment']); cat=st.selectbox('Category',[c['name'] for c in st.session_state.categories]);
        if st.form_submit_button('Add Transaction'): st.session_state.transactions.append({'id':str(uuid.uuid4()),'title':title,'amount':amount,'type':typ,'category':cat,'date':date.today().isoformat(),'payment':'UPI'}); persist(); st.session_state.quick=False; st.rerun()

def main():
    inject_css()
    if 'profile' not in st.session_state: reset_workspace()
    if not st.session_state.profile.get('is_logged_in',False): auth_page(); return
    if 'page' not in st.session_state: st.session_state.page='dashboard'
    if 'chat' not in st.session_state: st.session_state.chat=[]
    sidebar(); topbar()
    if st.session_state.get('quick'): quick_add(); st.divider()
    pages={'dashboard':dashboard,'personal':personal,'transactions':transactions,'goals':goals,'risk':risk,'planner':planner,'simulator':simulator,'whatif':whatif,'analytics':analytics,'copilot':copilot,'authenticate':authenticate,'settings':settings}
    pages[st.session_state.page](); persist()

main()

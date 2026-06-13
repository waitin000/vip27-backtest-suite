"""Quantify the difference between walk-forward and full backtest for the 5-symbol portfolio"""
import pickle, zipfile, os, requests, json
import numpy as np
import pandas as pd

# ===== Part 1: Walk-forward results (from ablation pkl) =====
z = zipfile.ZipFile('C:/Users/boris/Desktop/VIP27_optimized.ZIP')
data = pickle.load(z.open('backtest_results_ext/ext20_ablation_results.pkl'))
opt = 'remove_kg_liqka_n4'

symbols = ['a888','hc888','i888','j888','ma888']
name_map = {'a888':'豆一','hc888':'热卷','i888':'铁矿','j888':'焦炭','ma888':'甲醇'}

# Ablation: walk-forward monthly PnL (1 lot each)
ablation_wf = {sym: [] for sym in symbols}
ablation_wf_total = {sym: 0 for sym in symbols}

all_months = sorted(set(w['test_month'] for w in data[opt][symbols[0]]))
for sym in symbols:
    for mo in all_months:
        for w in data[opt][sym]:
            if w['test_month'] == mo:
                ablation_wf[sym].append(float(w['test_pnl']))
                ablation_wf_total[sym] += float(w['test_pnl'])
                break

# ===== Part 2: Full backtest results (from the trade-level script) =====
# Run full backtest (same logic as the trade-level script, just get monthly totals)
API_URL = 'http://121.237.178.245:8086/futures/history'
AUTH = {'username': '13621640810', 'password': 'Sherl0cked?'}
DATA_DIR = 'C:/tmp/v27_portfolio_data'

CONTRACT_INFO = {
    'a888': {'mult':10,'commission':0.00010}, 'hc888':{'mult':10,'commission':0.00010},
    'i888': {'mult':100,'commission':0.00010}, 'j888':{'mult':100,'commission':0.00010},
    'ma888':{'mult':10,'commission':0.00010},
}

def compute_indicators(df, params):
    open_p=df['open'].values; high=df['high'].values; low=df['low'].values
    close=df['close'].values; n=len(df)
    atr_len=params.get('atr_length',55); atr_mult_b=params.get('atr_mult',3.0)
    rs=params.get('radius_strength',0.05); sm=params.get('smoothness',5)
    n_per=params.get('n_period',5)
    tr=np.zeros(n); tr[0]=high[0]-low[0]
    for i in range(1,n): tr[i]=max(high[i]-low[i],abs(high[i]-close[i-1]),abs(low[i]-close[i-1]))
    atr=pd.Series(tr).rolling(atr_len,min_periods=1).mean().values
    am=np.full(n,atr_mult_b)
    src=(high+low)/2; upper=src+am*atr; lower=src-am*atr
    dr=np.ones(n,dtype=int); sb=np.zeros(n); sb[0]=lower[0]
    for i in range(1,n):
        if np.isnan(upper[i]) or np.isnan(lower[i]): dr[i]=dr[i-1]; sb[i]=sb[i-1]; continue
        if dr[i-1]==1:
            if close[i]<sb[i-1]: sb[i]=upper[i]; dr[i]=-1
            else: sb[i]=max(lower[i],sb[i-1]); dr[i]=1
        else:
            if close[i]>sb[i-1]: sb[i]=lower[i]; dr[i]=1
            else: sb[i]=min(upper[i],sb[i-1]); dr[i]=-1
    st=sb.copy(); ca=sb[0]; cv=0; cb=0
    for i in range(1,n):
        if dr[i]!=dr[i-1]: ca=sb[i]; cb=0; cv=0
        cb+=1; cv+=rs*cb
        st[i]=ca+cv if dr[i]==1 else ca-cv
    curved=pd.Series(st).rolling(sm,min_periods=1).mean().values
    kg=np.zeros(n); chg=np.zeros(n)
    for i in range(1,n): chg[i]=curved[i]-curved[i-1]
    for i in range(2,n):
        if dr[i]==1:
            if (chg[i]>0 and chg[i-1]<0) or (dr[i]==1 and dr[i-1]==-1): kg[i]=1
        else:
            if (chg[i]<0 and chg[i-1]>0) or (dr[i]==-1 and dr[i-1]==1): kg[i]=-1
    hh=np.zeros(n); ll=np.zeros(n)
    for i in range(n_per,n): hh[i]=np.max(high[i-n_per:i]); ll[i]=np.min(low[i-n_per:i])
    return {'open':open_p,'high':high,'low':low,'close':close,'direction':dr,
            'kg_signal':kg,'hh':hh,'ll':ll,'atr':atr,'atr_mult':am}

def full_backtest(sym):
    csv_path = os.path.join(DATA_DIR, f'{sym}_30m.csv')
    if not os.path.exists(csv_path):
        params={'symbol':sym,'period':'30m','adjust_type':'0','limit':50000,**AUTH}
        r=requests.get(API_URL,params=params,timeout=60)
        klines=r.json().get('data',{}).get('klines',[]); df=pd.DataFrame(klines)
        df['datetime']=pd.to_datetime(df['datetime']); df=df.sort_values('datetime').set_index('datetime')
        for c in ['open','high','low','close','volume']: df[c]=pd.to_numeric(df[c],errors='coerce')
        df=df[['open','high','low','close','volume']].dropna(); df.to_csv(csv_path)
    else: df=pd.read_csv(csv_path,index_col='datetime',parse_dates=True)
    
    dates=df.index; ci=CONTRACT_INFO[sym]; mult=ci['mult']; comm_rate=ci['commission']
    p={
        'atr_length':55,'atr_mult':3.0,'n_period':5,
        'radius_strength':0.05,'smoothness':5,'trailing_stop_rate':40,
        'use_kg':False,'use_n_breakout':True,'use_liqka_stop':True,'use_trend_exit':True,
    }
    data=compute_indicators(df,p)
    dr=data['direction']; atr=data['atr']; kg=data['kg_signal']; hh=data['hh']; ll=data['ll']
    opens,highs,lows,closes=df['open'].values,df['high'].values,df['low'].values,df['close'].values
    tsr=40/1000.0; liqka_min=0.5; atr_len=55; n_per=5
    
    pos=0; ep=0.0; eb=0; hl=0.0; lh=999999.0; liqka=1.0
    monthly={}
    
    for i in range(max(atr_len,n_per)+1,len(closes)):
        if pos!=0 and i>eb:
            if True:
                liqka=max(liqka-0.1,liqka_min)
                if pos>0:
                    hl=max(hl,lows[i]); dliq=hl-(opens[i]*tsr)*liqka
                    if lows[i]<=dliq:
                        exp=min(opens[i],dliq); pnl=(exp-ep)*mult; net=pnl-abs(pnl)*comm_rate
                        ym=dates[eb].strftime('%Y-%m'); monthly[ym]=monthly.get(ym,0)+net
                        pos=0; liqka=1.0; continue
                elif pos<0:
                    lh=min(lh,highs[i]); kliq=lh+(opens[i]*tsr)*liqka
                    if highs[i]>=kliq:
                        exp=max(opens[i],kliq); pnl=(ep-exp)*mult; net=pnl-abs(pnl)*comm_rate
                        ym=dates[eb].strftime('%Y-%m'); monthly[ym]=monthly.get(ym,0)+net
                        pos=0; liqka=1.0; continue
            if True and i>0:
                if pos>0 and dr[i]==-1:
                    exp=opens[i]; pnl=(exp-ep)*mult; net=pnl-abs(pnl)*comm_rate
                    ym=dates[eb].strftime('%Y-%m'); monthly[ym]=monthly.get(ym,0)+net
                    pos=0; liqka=1.0; continue
                elif pos<0 and dr[i]==1:
                    exp=opens[i]; pnl=(ep-exp)*mult; net=pnl-abs(pnl)*comm_rate
                    ym=dates[eb].strftime('%Y-%m'); monthly[ym]=monthly.get(ym,0)+net
                    pos=0; liqka=1.0; continue
        
        if pos==0:
            lo=False; so=False
            if i>0 and dr[i]!=dr[i-1]:
                if dr[i]==1: lo=True
                elif dr[i]==-1: so=True
            if True and (lo or so):
                if lo and i>0:
                    hhn=np.max(highs[max(0,i-n_per):i]) if i>=n_per else highs[i]
                    lo=lo and (highs[i]>hhn)
                if so and i>0:
                    lln=np.min(lows[max(0,i-n_per):i]) if i>=n_per else lows[i]
                    so=so and (lows[i]<lln)
            if lo: pos=1; ep=opens[i]; eb=i; hl=lows[i]; liqka=1.0
            elif so: pos=-1; ep=opens[i]; eb=i; lh=highs[i]; liqka=1.0
    
    return monthly

print("Running full backtest for 5 symbols...")
full_monthly = {}
for sym in symbols:
    full_monthly[sym] = full_backtest(sym)
    print(f"  {sym}: done")

# ===== Compare =====
print("\n" + "=" * 85)
print("Walk-Forward vs 全量一次性回测: 5品种组合各1手 逐月PnL对比")
print("=" * 85)

wf_months = all_months  # ['2025-01' ... '2026-06']

print(f"{'月份':>8} | {'WF总PnL':>10} | {'全量总PnL':>10} | {'差额':>10} | {'差额%':>8}")
print("-" * 55)

total_wf = 0
total_full = 0

for mo in wf_months:
    wf_sum = sum(ablation_wf[sym][wf_months.index(mo)] for sym in symbols)
    full_sum = sum(full_monthly[sym].get(mo, 0) for sym in symbols)
    total_wf += wf_sum
    total_full += full_sum
    diff = wf_sum - full_sum
    diff_pct = diff / full_sum * 100 if full_sum != 0 else 0
    print(f"  {mo:>8} | {wf_sum:>+9,.0f} | {full_sum:>+9,.0f} | {diff:>+9,.0f} | {diff_pct:>+7.0f}%")

print("-" * 55)
print(f"  {'合计':>8} | {total_wf:>+9,.0f} | {total_full:>+9,.0f} | {total_wf-total_full:>+9,.0f}")

# 2026 only
print(f"\n--- 2026年对比 ---")
total_wf_2026 = 0
total_full_2026 = 0
for mo in [m for m in wf_months if m.startswith('2026')]:
    wf_sum = sum(ablation_wf[sym][wf_months.index(mo)] for sym in symbols)
    full_sum = sum(full_monthly[sym].get(mo, 0) for sym in symbols)
    total_wf_2026 += wf_sum
    total_full_2026 += full_sum
    diff = wf_sum - full_sum
    diff_pct = diff / full_sum * 100 if full_sum != 0 else 0
    print(f"  {mo:>8} | {wf_sum:>+9,.0f} | {full_sum:>+9,.0f} | {diff:>+9,.0f} | {diff_pct:>+7.0f}%")

print("-" * 55)
print(f"  {'合计2026':>8} | {total_wf_2026:>+9,.0f} | {total_full_2026:>+9,.0f} | {total_wf_2026-total_full_2026:>+9,.0f}")

# Per-symbol totals
print(f"\n--- 各品种全期合计 ---")
print(f"{'品种':>8} | {'WF总PnL':>10} | {'全量总PnL':>10} | {'差额':>10}")
print("-" * 45)
for sym in symbols:
    wf_s = ablation_wf_total[sym]
    full_s = sum(full_monthly[sym].values())
    print(f"  {name_map[sym]:>8} | {wf_s:>+9,.0f} | {full_s:>+9,.0f} | {wf_s-full_s:>+9,.0f}")

# Correlation analysis
print(f"\n--- 相关性分析 ---")
wf_series = []
full_series = []
for mo in wf_months:
    wf_series.append(sum(ablation_wf[sym][wf_months.index(mo)] for sym in symbols))
    full_series.append(sum(full_monthly[sym].get(mo, 0) for sym in symbols))

wf_arr = np.array(wf_series)
full_arr = np.array(full_series)
corr = np.corrcoef(wf_arr, full_arr)[0, 1]
print(f"  逐月PnL相关系数: {corr:.3f}")

wf_cum = np.cumsum(wf_arr)
full_cum = np.cumsum(full_arr)
corr_cum = np.corrcoef(wf_cum, full_cum)[0, 1]
print(f"  累计PnL相关系数: {corr_cum:.3f}")

print(f"\n  WF总PnL: {total_wf:+,.0f}")
print(f"  全量总PnL: {total_full:+,.0f}")
print(f"  差额: {total_wf-total_full:+,.0f}")
print(f"  差额占WF比例: {(total_wf-total_full)/abs(total_wf)*100:.0f}%" if total_wf != 0 else "WF总PnL为0")

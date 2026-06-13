#!/usr/bin/env python3
"""
5品种组合逐笔交易回测&逐笔记录生成器
组合: 豆一(a888) + 热卷(hc888) + 铁矿(i888) + 焦炭(j888) + 甲醇(ma888)

两种仓位方案:
  A. 各1手（5手）
  B. 等风险加权（豆一8手,热卷7手,铁矿3手,焦炭1手,甲醇11手）

跑2026-01~2026-06逐笔交易记录，输出到HTML
"""
import sys, os, time, pickle, json
import numpy as np
import pandas as pd
import requests

# ── 配置 ──
API_URL = 'http://121.237.178.245:8086/futures/history'
AUTH = {'username': '13621640810', 'password': 'Sherl0cked?'}

CONTRACT_INFO = {
    'a888':  {'mult': 10,  'commission': 0.00010, 'tick': 1},
    'hc888': {'mult': 10,  'commission': 0.00010, 'tick': 1},
    'i888':  {'mult': 100, 'commission': 0.00010, 'tick': 0.5},
    'j888':  {'mult': 100, 'commission': 0.00010, 'tick': 0.5},
    'ma888': {'mult': 10,  'commission': 0.00010, 'tick': 1},
}
NAME_MAP = {'a888':'豆一','hc888':'热卷','i888':'铁矿','j888':'焦炭','ma888':'甲醇'}
DATA_DIR = 'C:/tmp/v27_portfolio_data'
os.makedirs(DATA_DIR, exist_ok=True)

# 仓位方案
POSITION_PLANS = {
    '各1手':   {'a888':1,'hc888':1,'i888':1,'j888':1,'ma888':1},
    '等风险加权': {'a888':8,'hc888':7,'i888':3,'j888':1,'ma888':11},
}

SYMBOLS = ['a888','hc888','i888','j888','ma888']

# ── Step 1: 拉取数据 ──
def fetch_data():
    print("Fetching 30m data for 5 symbols...")
    for sym in SYMBOLS:
        cache = os.path.join(DATA_DIR, f'{sym}_30m.csv')
        params = {'symbol': sym, 'period': '30m', 'adjust_type': '0', 'limit': 50000, **AUTH}
        r = requests.get(API_URL, params=params, timeout=60)
        if r.status_code == 200:
            klines = r.json().get('data', {}).get('klines', [])
            if klines:
                df = pd.DataFrame(klines)
                df['datetime'] = pd.to_datetime(df['datetime'])
                df = df.sort_values('datetime').set_index('datetime')
                for col in ['open','high','low','close','volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                df = df[['open','high','low','close','volume']].dropna()
                df.to_csv(cache)
                print(f"  {sym}: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')} ({len(df)} bars)")
    print("Done.\n")

# ── Step 2: 从wm_vip27_optimized.py导入策略逻辑 ──
# 直接内联 compute_indicators_optimized 和 detailed_backtest

def compute_indicators_optimized(df, params):
    """Compute all indicators (same as wm_vip27_optimized.py)"""
    open_p = df['open'].values
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    volume = df['volume'].values
    n = len(df)
    
    atr_len = params.get('atr_length', 55)
    atr_mult_base = params.get('atr_mult', 3.0)
    rs = params.get('radius_strength', 0.05)
    sm = params.get('smoothness', 5)
    n_per = params.get('n_period', 5)
    
    # ATR
    tr_arr = np.zeros(n)
    tr_arr[0] = high[0] - low[0]
    for i in range(1, n):
        tr_arr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr = pd.Series(tr_arr).rolling(atr_len, min_periods=1).mean().values
    
    atr_mult_arr = np.full(n, atr_mult_base)
    
    # SuperTrend bands
    src = (high + low) / 2.0
    upper = src + atr_mult_arr * atr
    lower = src - atr_mult_arr * atr
    
    # Direction
    dr = np.ones(n, dtype=int)
    st_base = np.zeros(n)
    st_base[0] = lower[0]
    for i in range(1, n):
        if np.isnan(upper[i]) or np.isnan(lower[i]):
            dr[i] = dr[i-1]
            st_base[i] = st_base[i-1]
            continue
        if dr[i-1] == 1:
            if close[i] < st_base[i-1]:
                st_base[i] = upper[i]; dr[i] = -1
            else:
                st_base[i] = max(lower[i], st_base[i-1]); dr[i] = 1
        else:
            if close[i] > st_base[i-1]:
                st_base[i] = lower[i]; dr[i] = 1
            else:
                st_base[i] = min(upper[i], st_base[i-1]); dr[i] = -1
    
    # Curvature
    st = st_base.copy()
    cur_anchor = st_base[0]
    cur_vel, cur_bc = 0.0, 0
    for i in range(1, n):
        if dr[i] != dr[i-1]:
            cur_anchor = st_base[i]; cur_bc = 0; cur_vel = 0.0
        cur_bc += 1
        cur_vel += rs * cur_bc
        st[i] = cur_anchor + cur_vel if dr[i] == 1 else cur_anchor - cur_vel
    curved = pd.Series(st).rolling(sm, min_periods=1).mean().values
    
    # KG拐点
    kg = np.zeros(n)
    chg = np.zeros(n)
    for i in range(1, n):
        chg[i] = curved[i] - curved[i-1]
    for i in range(2, n):
        if dr[i] == 1:
            if (chg[i] > 0 and chg[i-1] < 0) or (dr[i]==1 and dr[i-1]==-1):
                kg[i] = 1
        else:
            if (chg[i] < 0 and chg[i-1] > 0) or (dr[i]==-1 and dr[i-1]==1):
                kg[i] = -1
    
    # N周期突破
    hh = np.zeros(n)
    ll = np.zeros(n)
    for i in range(n_per, n):
        hh[i] = np.max(high[i-n_per:i])
        ll[i] = np.min(low[i-n_per:i])
    
    # MA60
    ma_long = pd.Series(close).rolling(60, min_periods=1).mean().values
    
    return {
        'open': open_p, 'high': high, 'low': low, 'close': close, 'volume': volume,
        'direction': dr, 'supertrend': st, 'curved_band': curved,
        'kg_signal': kg, 'hh': hh, 'll': ll,
        'atr': atr, 'atr_mult': atr_mult_arr,
        'ma_long': ma_long,
    }

def detailed_backtest(data, params, symbol, mult, comm_rate, dates_arr):
    """Full backtest with trade-level logging, returns list of trades"""
    use_kg = params.get('use_kg', True)
    use_n_breakout = params.get('use_n_breakout', True)
    use_liqka_stop = params.get('use_liqka_stop', True)
    use_trend_exit = params.get('use_trend_exit', True)
    tsr = params.get('trailing_stop_rate', 40) / 1000.0
    liqka_min = params.get('liqka_min', 0.5)
    atr_len = params.get('atr_length', 55)
    n_per = params.get('n_period', 5)
    
    direction = data['direction']
    kg = data['kg_signal']
    hh = data['hh']
    ll = data['ll']
    atr = data['atr']
    opens = data['open']
    highs = data['high']
    lows = data['low']
    closes = data['close']
    
    n = len(closes)
    pos = 0
    entry_price = 0.0
    entry_bar = 0
    h_l = 0.0
    l_h = 999999.0
    liqka = 1.0
    trades = []
    
    for i in range(max(atr_len, n_per) + 1, n):
        cur_date = str(dates_arr[i])[:19] if dates_arr is not None else ''
        
        # Stop
        if pos != 0 and i > entry_bar:
            if use_liqka_stop:
                liqka = max(liqka - 0.1, liqka_min)
                if pos > 0:
                    h_l = max(h_l, lows[i])
                    dliq = h_l - (opens[i] * tsr) * liqka
                    if lows[i] <= dliq:
                        ep = min(opens[i], dliq)
                        pnl = (ep - entry_price) * mult
                        net = pnl - abs(pnl) * comm_rate
                        trades.append({'dir':'多','entry_date':entry_date,'exit_date':cur_date,
                            'entry_price':entry_price,'exit_price':ep,'pnl':net,'pts':pnl/mult,'reason':'LiqKA止损'})
                        pos = 0; liqka = 1.0; continue
                elif pos < 0:
                    l_h = min(l_h, highs[i])
                    kliq = l_h + (opens[i] * tsr) * liqka
                    if highs[i] >= kliq:
                        ep = max(opens[i], kliq)
                        pnl = (entry_price - ep) * mult
                        net = pnl - abs(pnl) * comm_rate
                        trades.append({'dir':'空','entry_date':entry_date,'exit_date':cur_date,
                            'entry_price':entry_price,'exit_price':ep,'pnl':net,'pts':pnl/mult,'reason':'LiqKA止损'})
                        pos = 0; liqka = 1.0; continue
            
            if use_trend_exit and i > 0:
                if pos > 0 and direction[i] == -1:
                    ep = opens[i]
                    pnl = (ep - entry_price) * mult; net = pnl - abs(pnl) * comm_rate
                    trades.append({'dir':'多','entry_date':entry_date,'exit_date':cur_date,
                        'entry_price':entry_price,'exit_price':ep,'pnl':net,'pts':pnl/mult,'reason':'趋势反转'})
                    pos = 0; liqka = 1.0; continue
                elif pos < 0 and direction[i] == 1:
                    ep = opens[i]
                    pnl = (entry_price - ep) * mult; net = pnl - abs(pnl) * comm_rate
                    trades.append({'dir':'空','entry_date':entry_date,'exit_date':cur_date,
                        'entry_price':entry_price,'exit_price':ep,'pnl':net,'pts':pnl/mult,'reason':'趋势反转'})
                    pos = 0; liqka = 1.0; continue
        
        # Entry
        if pos == 0:
            long_ok = False; short_ok = False
            if use_kg:
                kg_prev = kg[i-1] if i > 0 else 0
                dr_prev = direction[i-1] if i > 0 else 0
                long_ok = (kg_prev == 1 and dr_prev == 1)
                short_ok = (kg_prev == -1 and dr_prev == -1)
                if use_n_breakout and (long_ok or short_ok):
                    if long_ok and i > 0 and hh[i-1] > 0:
                        long_ok = long_ok and (highs[i] > hh[i-1])
                    if short_ok and i > 0 and ll[i-1] > 0:
                        short_ok = short_ok and (lows[i] < ll[i-1])
            else:
                if i > 0 and direction[i] != direction[i-1]:
                    if direction[i] == 1: long_ok = True
                    elif direction[i] == -1: short_ok = True
                if use_n_breakout and (long_ok or short_ok):
                    if long_ok and i > 0 and hh[i-1] > 0:
                        long_ok = long_ok and (highs[i] > hh[i-1])
                    if short_ok and i > 0 and ll[i-1] > 0:
                        short_ok = short_ok and (lows[i] < ll[i-1])
            
            if long_ok:
                pos = 1; entry_price = opens[i]; entry_bar = i
                entry_date = cur_date; h_l = lows[i]; liqka = 1.0
            elif short_ok:
                pos = -1; entry_price = opens[i]; entry_bar = i
                entry_date = cur_date; l_h = highs[i]; liqka = 1.0
    
    # Close at end
    if pos != 0:
        ep = closes[-1]
        if pos > 0: pnl = (ep - entry_price) * mult
        else: pnl = (entry_price - ep) * mult
        net = pnl - abs(pnl) * comm_rate
        trades.append({'dir':'多' if pos>0 else '空','entry_date':entry_date,'exit_date':str(dates_arr[-1])[:19],
            'entry_price':entry_price,'exit_price':ep,'pnl':net,'pts':pnl/mult,'reason':'期末平仓'})
    
    return trades

def run_backtest_for_plan(plan_name, lots_dict):
    """Run full backtest for all 5 symbols, return trade records"""
    print(f"\n{'='*60}")
    print(f"  回测方案: {plan_name}")
    print(f"{'='*60}")
    
    all_trades = []  # (sym, trade_dict)
    
    for sym in SYMBOLS:
        lots = lots_dict[sym]
        ci = CONTRACT_INFO[sym]
        mult = ci['mult']
        comm_rate = ci['commission']
        
        # Load data
        csv_path = os.path.join(DATA_DIR, f'{sym}_30m.csv')
        df = pd.read_csv(csv_path, index_col='datetime', parse_dates=True)
        
        # Use all data from beginning
        dates = np.array([str(d) for d in df.index])
        
        # Optimized params (remove_kg variant)
        params = {
            'atr_length': 55, 'atr_mult': 3.0, 'n_period': 5,
            'radius_strength': 0.05, 'smoothness': 5, 'trailing_stop_rate': 40,
            'use_kg': False, 'use_n_breakout': True, 'use_liqka_stop': True,
            'use_trend_exit': True,
        }
        
        # Compute indicators on full data
        data = compute_indicators_optimized(df, params)
        data['dates'] = dates  # not used in this version
        
        # Run detailed backtest on ALL data
        trades = detailed_backtest(data, params, sym, mult, comm_rate, dates)
        
        # Apply lot multiplier
        for t in trades:
            t['pnl'] *= lots
            t['symbol'] = sym
            t['name'] = NAME_MAP[sym]
            t['lots'] = lots
        
        all_trades.extend(trades)
        print(f"  {sym} ({NAME_MAP[sym]}): {len(trades)} 笔 (x{lots}手)")
    
    return all_trades

def generate_html(plan_name, trades_all):
    """Generate detailed trade log HTML"""
    import base64
    
    # Filter to 2026 only
    trades_2026 = [t for t in trades_all if t['entry_date'].startswith('2026')]
    trades_2026.sort(key=lambda t: t['entry_date'])
    
    # Monthly summary
    monthly = {}
    for t in trades_2026:
        ym = t['entry_date'][:7]
        if ym not in monthly:
            monthly[ym] = {'trades':[], 'pnl':0, 'wins':0, 'losses':0}
        monthly[ym]['trades'].append(t)
        monthly[ym]['pnl'] += t['pnl']
        if t['pnl'] > 0: monthly[ym]['wins'] += 1
        elif t['pnl'] < 0: monthly[ym]['losses'] += 1
    
    total_pnl = sum(t['pnl'] for t in trades_2026)
    total_wins = sum(1 for t in trades_2026 if t['pnl'] > 0)
    total_losses = sum(1 for t in trades_2026 if t['pnl'] < 0)
    
    all_sym_pnl = {}
    for t in trades_2026:
        all_sym_pnl.setdefault(t['symbol'], 0)
        all_sym_pnl[t['symbol']] += t['pnl']
    
    # Build HTML
    css = '*{margin:0;padding:0;box-sizing:border-box}body{background:#0f172a;color:#e2e8f0;font-family:sans-serif;padding:16px}.container{max-width:1200px;margin:0 auto}.header{text-align:center;padding:20px 0;}.header h1{font-size:22px;font-weight:700;background:linear-gradient(135deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}.header p{color:#94a3b8;font-size:13px}.card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:16px;margin-top:12px}.card h2{font-size:14px;font-weight:600;color:#94a3b8;margin-bottom:10px}.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin-top:10px}.stat{background:#0f172a;border-radius:6px;padding:10px;text-align:center}.stat .l{font-size:10px;color:#64748b;text-transform:uppercase}.stat .v{font-size:16px;font-weight:700;margin-top:2px}.g{color:#22c55e}.r{color:#ef4444}.b{color:#3b82f6}.a{color:#f59e0b}table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}th{text-align:right;padding:6px 8px;color:#64748b;font-weight:600;border-bottom:1px solid #334155;position:sticky;top:0;background:#1e293b}th:first-child,td:first-child{text-align:left}td{text-align:right;padding:4px 8px;border-bottom:1px solid #1e293b;font-variant-numeric:tabular-nums}.tc{max-height:500px;overflow-y:auto}.tc::-webkit-scrollbar{width:6px}.tc::-webkit-scrollbar-track{background:#0f172a}.tc::-webkit-scrollbar-thumb{background:#475569;border-radius:3px}.month-title{font-size:14px;font-weight:600;color:#f59e0b;padding:8px 0 4px;border-bottom:1px solid #334155;margin-top:16px}.tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600}.tag-a888{background:#065f46;color:#6ee7b7}.tag-hc888{background:#1e3a5f;color:#93c5fd}.tag-i888{background:#5b2d8b;color:#c4b5fd}.tag-j888{background:#78350f;color:#fdba74}.tag-ma888{background:#6b1d3d;color:#f9a8d4}.footer{text-align:center;color:#475569;font-size:11px;margin-top:20px;padding:12px;border-top:1px solid #1e293b}'

    sym_tags = {'a888':'tag-a888','hc888':'tag-hc888','i888':'tag-i888','j888':'tag-j888','ma888':'tag-ma888'}
    
    html = '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>5品种组合 2026年逐笔交易 - ' + plan_name + '</title><style>' + css + '</style></head><body><div class="container">'
    
    html += '<div class="header"><h1>均衡-黑色系 5品种组合</h1><p>' + plan_name + ' · 2026年1月~6月 · 全部逐笔交易</p></div>'
    
    # Summary stats
    html += '<div class="card"><h2>总体统计</h2><div class="stats">'
    html += '<div class="stat"><div class="l">总PnL</div><div class="v ' + ('g' if total_pnl>=0 else 'r') + '">' + ('%+d' % total_pnl) + '</div></div>'
    html += '<div class="stat"><div class="l">总交易</div><div class="v">' + str(len(trades_2026)) + '笔</div></div>'
    html += '<div class="stat"><div class="l">胜/负</div><div class="v">' + str(total_wins) + '/' + str(total_losses) + '</div></div>'
    html += '<div class="stat"><div class="l">胜率</div><div class="v g">' + ('%.0f' % (total_wins/max(len(trades_2026),1)*100)) + '%</div></div>'
    for sym in SYMBOLS:
        pnl = all_sym_pnl.get(sym, 0)
        html += '<div class="stat"><div class="l">' + NAME_MAP[sym] + '</div><div class="v ' + ('g' if pnl>=0 else 'r') + '">' + ('%+d' % pnl) + '</div></div>'
    html += '</div></div>'
    
    # Monthly summary
    html += '<div class="card"><h2>月度汇总</h2><table><tr><th>月份</th><th>笔数</th><th>胜/负</th><th>胜率</th><th>总PnL</th></tr>'
    for ym in sorted(monthly.keys()):
        md = monthly[ym]
        wr = md['wins']/max(len(md['trades']),1)*100
        html += '<tr><td>' + ym + '</td><td>' + str(len(md['trades'])) + '</td><td>' + str(md['wins']) + '/' + str(md['losses']) + '</td><td>' + ('%.0f' % wr) + '%</td><td style="color:' + ('#22c55e' if md['pnl']>=0 else '#ef4444') + '">' + ('%+d' % md['pnl']) + '</td></tr>'
    html += '</table></div>'
    
    # Per-symbol monthly
    html += '<div class="card"><h2>逐品种月度PnL</h2><table><tr><th>月份</th>'
    for sym in SYMBOLS:
        html += '<th>' + NAME_MAP[sym] + '</th>'
    html += '<th>合计</th></tr>'
    for ym in sorted(monthly.keys()):
        html += '<tr><td>' + ym + '</td>'
        ym_total = 0
        for sym in SYMBOLS:
            sp = sum(t['pnl'] for t in trades_2026 if t['entry_date'].startswith(ym) and t['symbol'] == sym)
            ym_total += sp
            html += '<td style="color:' + ('#22c55e' if sp>=0 else '#ef4444') + '">' + ('%+d' % sp) + '</td>'
        html += '<td style="color:' + ('#22c55e' if ym_total>=0 else '#ef4444') + ';font-weight:700">' + ('%+d' % ym_total) + '</td></tr>'
    html += '</table></div>'
    
    # All trades detail
    html += '<div class="card"><h2>逐笔交易明细</h2><div class="tc"><table><tr><th>日期</th><th>品种</th><th>方向</th><th>手数</th><th>入场价</th><th>出场价</th><th>盈亏(元)</th><th>盈亏(点)</th><th>原因</th></tr>'
    for t in trades_2026:
        html += '<tr>'
        html += '<td>' + t['entry_date'][:16] + '</td>'
        html += '<td><span class="tag ' + sym_tags[t['symbol']] + '">' + t['name'] + '</span></td>'
        html += '<td>' + t['dir'] + '</td>'
        html += '<td>' + str(t['lots']) + '</td>'
        html += '<td>%.1f' % t['entry_price'] + '</td>'
        html += '<td>%.1f' % t['exit_price'] + '</td>'
        html += '<td style="color:' + ('#22c55e' if t['pnl']>=0 else '#ef4444') + '">' + ('%+d' % t['pnl']) + '</td>'
        html += '<td>' + ('%+.1f' % t['pts']) + '</td>'
        html += '<td style="color:#64748b;font-size:11px">' + t['reason'] + '</td>'
        html += '</tr>'
    html += '</table></div></div>'
    
    html += '<div class="footer">数据生成: VIP27优化策略(删KG) · 参数: atr=55, mult=3, N=5, radius=0.05, stop=40</div>'
    html += '</div></body></html>'
    
    return html

# ── Main ──
def main():
    fetch_data()
    
    for plan_name, lots_dict in POSITION_PLANS.items():
        trades = run_backtest_for_plan(plan_name, lots_dict)
        html = generate_html(plan_name, trades)
        
        out_path = f'C:/Users/boris/Desktop/portfolio_2026_trades_{plan_name}.html'
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"  HTML saved: {out_path}")
    
    print("\nDone!")

if __name__ == '__main__':
    main()

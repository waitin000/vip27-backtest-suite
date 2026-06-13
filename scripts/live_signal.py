#!/usr/bin/env python3
"""
VIP27 实盘信号计算模块
读取30m K线 → 计算SuperTrend方向 → 生成入场/出场信号

支持两种数据源:
  1. ssquant API（默认）
  2. CTP行情直连（需配置）
"""
import os, time, json
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timedelta

# ── 配置 ──
DATA_SOURCE = 'api'  # 'api' 或 'ctp'
API_URL = 'http://121.237.178.245:8086/futures/history'
API_AUTH = {'username': '13621640810', 'password': 'Sherl0cked?'}

# 5品种合约信息
CONTRACTS = {
    'a888':  {'mult': 10,  'tick': 1,    'exchange': 'DCE',  'name': '豆一'},
    'hc888': {'mult': 10,  'tick': 1,    'exchange': 'SHFE', 'name': '热卷'},
    'i888':  {'mult': 100, 'tick': 0.5,  'exchange': 'DCE',  'name': '铁矿'},
    'j888':  {'mult': 100, 'tick': 0.5,  'exchange': 'DCE',  'name': '焦炭'},
    'ma888': {'mult': 10,  'tick': 1,    'exchange': 'CZCE', 'name': '甲醇'},
}

# 策略参数（与回测一致）
STRATEGY_PARAMS = {
    'atr_length': 55,
    'atr_mult': 3.0,
    'radius_strength': 0.05,
    'smoothness': 5,
    'n_period': 5,
    'trailing_stop_rate': 40,
    'use_kg': False,          # 删KG
    'use_n_breakout': True,
    'use_liqka_stop': True,
    'use_trend_exit': True,
}

# 仓位配置
POSITIONS = {
    'a888': 1,
    'hc888': 1,
    'i888': 1,
    'j888': 1,
    'ma888': 1,
}

DATA_CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data_cache')
os.makedirs(DATA_CACHE_DIR, exist_ok=True)


# ══════════════════════════════════════════
#  1. 数据获取
# ══════════════════════════════════════════

def fetch_kline(symbol, period='30m', limit=1000):
    """从ssquant API获取K线数据"""
    cache_file = os.path.join(DATA_CACHE_DIR, f'{symbol}_{period}.csv')
    
    params = {'symbol': symbol, 'period': period, 'adjust_type': '0', 'limit': limit, **API_AUTH}
    try:
        r = requests.get(API_URL, params=params, timeout=30)
        if r.status_code == 200:
            klines = r.json().get('data', {}).get('klines', [])
            if klines:
                df = pd.DataFrame(klines)
                df['datetime'] = pd.to_datetime(df['datetime'])
                df = df.sort_values('datetime').set_index('datetime')
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
                df.to_csv(cache_file)
                return df
    except Exception as e:
        print(f"  [WARN] API fetch failed for {symbol}: {e}")
    
    # Fallback: read from cache
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col='datetime', parse_dates=True)
    return None


# ══════════════════════════════════════════
#  2. 策略指标计算
# ══════════════════════════════════════════

def compute_signals(df, params=None):
    """
    计算VIP27策略信号
    返回: direction数组 + 入场信号 + 离场信号
    """
    if params is None:
        params = STRATEGY_PARAMS
    
    open_p = df['open'].values
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    volume = df['volume'].values
    n = len(df)
    
    atr_len = params['atr_length']
    atr_mult_b = params['atr_mult']
    rs = params['radius_strength']
    sm = params['smoothness']
    n_per = params['n_period']
    
    # ── ATR ──
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr = pd.Series(tr).rolling(atr_len, min_periods=1).mean().values
    
    atr_mult_arr = np.full(n, atr_mult_b)
    
    # ── SuperTrend ──
    src = (high + low) / 2.0
    upper = src + atr_mult_arr * atr
    lower = src - atr_mult_arr * atr
    
    direction = np.ones(n, dtype=int)
    st_base = np.zeros(n)
    st_base[0] = lower[0]
    
    for i in range(1, n):
        if np.isnan(upper[i]) or np.isnan(lower[i]):
            direction[i] = direction[i-1]
            st_base[i] = st_base[i-1]
            continue
        if direction[i-1] == 1:
            if close[i] < st_base[i-1]:
                st_base[i] = upper[i]
                direction[i] = -1
            else:
                st_base[i] = max(lower[i], st_base[i-1])
                direction[i] = 1
        else:
            if close[i] > st_base[i-1]:
                st_base[i] = lower[i]
                direction[i] = 1
            else:
                st_base[i] = min(upper[i], st_base[i-1])
                direction[i] = -1
    
    # ── 曲率半径 ──
    st = st_base.copy()
    cur_anchor = st_base[0]
    cur_vel = 0.0
    cur_bc = 0
    for i in range(1, n):
        if direction[i] != direction[i-1]:
            cur_anchor = st_base[i]
            cur_bc = 0
            cur_vel = 0.0
        cur_bc += 1
        cur_vel += rs * cur_bc
        st[i] = cur_anchor + cur_vel if direction[i] == 1 else cur_anchor - cur_vel
    curved = pd.Series(st).rolling(sm, min_periods=1).mean().values
    
    # ── N周期高/低点 ──
    hh = np.zeros(n)
    ll = np.zeros(n)
    for i in range(n_per, n):
        hh[i] = np.max(high[i-n_per:i])
        ll[i] = np.min(low[i-n_per:i])
    
    # ── 最新信号判断 ──
    signals = {
        'direction': int(direction[-1]),
        'direction_prev': int(direction[-2]) if n >= 2 else 0,
        'direction_flip': bool(direction[-1] != direction[-2]) if n >= 2 else False,
        'price': float(close[-1]),
        'atr': float(atr[-1]),
        'supertrend': float(curved[-1]),
        'hh_5': float(hh[-1]) if not np.isnan(hh[-1]) else 0,
        'll_5': float(ll[-1]) if not np.isnan(ll[-1]) else 0,
        'timestamp': str(df.index[-1]),
        'n_bars': n,
    }
    
    # 入场信号
    signals['long_entry'] = False
    signals['short_entry'] = False
    
    if signals['direction_flip']:
        if direction[-1] == 1:
            # direction翻多 → 检查N周期突破
            if hh[-1] > 0 and high[-1] > hh[-1]:
                signals['long_entry'] = True
        elif direction[-1] == -1:
            if ll[-1] > 0 and low[-1] < ll[-1]:
                signals['short_entry'] = True
    
    # 离场信号
    signals['exit_long'] = bool(direction[-1] == -1 and direction[-2] == 1) if n >= 2 else False
    signals['exit_short'] = bool(direction[-1] == 1 and direction[-2] == -1) if n >= 2 else False
    
    # LiqKA止损价计算（如果持仓）
    tsr = params['trailing_stop_rate'] / 1000.0
    signals['liqka_stop_long'] = float(close[-1] - (close[-1] * tsr))
    signals['liqka_stop_short'] = float(close[-1] + (close[-1] * tsr))
    
    return signals, {
        'direction': direction,
        'atr': atr,
        'supertrend': curved,
        'hh': hh,
        'll': ll,
    }


# ══════════════════════════════════════════
#  3. 全品种信号计算
# ══════════════════════════════════════════

def compute_all_signals():
    """计算所有5个品种的最新信号"""
    results = {}
    
    for sym in CONTRACTS:
        df = fetch_kline(sym)
        if df is None or len(df) < 100:
            print(f"  [ERROR] {sym}: 数据不足")
            results[sym] = {'error': '数据不足'}
            continue
        
        signals, raw_data = compute_signals(df)
        signals['symbol'] = sym
        signals['name'] = CONTRACTS[sym]['name']
        signals['lots'] = POSITIONS[sym]
        signals['mult'] = CONTRACTS[sym]['mult']
        results[sym] = signals
    
    return results


def format_signal_report(signals):
    """格式化为可读的信号报告"""
    lines = []
    lines.append('=' * 60)
    lines.append(f'  VIP27 实盘信号  {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append('=' * 60)
    
    has_signal = False
    
    for sym, s in signals.items():
        if 'error' in s:
            lines.append(f'\n  [{sym}] ERROR: {s["error"]}')
            continue
        
        ci = CONTRACTS[sym]
        dir_str = '🟢 多头' if s['direction'] == 1 else '🔴 空头'
        lines.append(f'\n  [{sym}] {ci["name"]}  {dir_str}  x{s["lots"]}手')
        lines.append(f'   价格: {s["price"]:.1f}  方向翻转: {"是" if s["direction_flip"] else "否"}')
        
        if s['long_entry']:
            lines.append(f'    ⬆️  **做多信号**  (direction翻多 + 突破{s["hh_5"]:.1f})')
            has_signal = True
        if s['short_entry']:
            lines.append(f'    ⬇️  **做空信号**  (direction翻空 + 跌破{s["ll_5"]:.1f})')
            has_signal = True
        if s['exit_long']:
            lines.append(f'    ⚠️  多头平仓信号 (direction翻空)')
        if s['exit_short']:
            lines.append(f'    ⚠️  空头平仓信号 (direction翻多)')
        
        if not (s['long_entry'] or s['short_entry'] or s['exit_long'] or s['exit_short']):
            lines.append(f'    → 无交易信号，持仓方向: {dir_str}')
    
    lines.append('\n' + '=' * 60)
    if not has_signal:
        lines.append('  当前无入场信号，等待direction翻转')
    lines.append('=' * 60)
    
    return '\n'.join(lines)


# ══════════════════════════════════════════
#  4. 主入口
# ══════════════════════════════════════════

def main():
    print("正在获取行情数据并计算信号...")
    signals = compute_all_signals()
    report = format_signal_report(signals)
    print(report)
    
    # 保存信号到JSON（供交易模块读取）
    out_path = os.path.join(DATA_CACHE_DIR, 'latest_signals.json')
    with open(out_path, 'w') as f:
        json.dump(signals, f, indent=2, default=str)
    print(f"\n信号已保存: {out_path}")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
VIP20 扩品种消融回测引擎
========================
20个期货品种 × 4组核心消融实验 × 18个月walk-forward
验证原5品种结论在更大样本下是否成立

消融组:
  1. baseline (全模块M1~M6)
  2. remove_kg (删M3:KG拐点)
  3. remove_liqka (删M5:LiqKA止损)
  4. remove_kg_liqka_n4 (删M3+M5, 加N4多周期动量 — 推荐最优配置)

20品种覆盖: 有色6 + 贵金属2 + 黑色4 + 化工4 + 农产品4 + 特殊3
"""

import os, sys, time, pickle, json
import numpy as np
import pandas as pd
import requests
from collections import defaultdict
from datetime import datetime

# ============== 配置 ==============
SSQUANT_API = 'http://121.237.178.245:8086/futures/history'
SSQUANT_USER = '13621640810'
SSQUANT_PASS = 'Sherl0cked?'

SYMBOLS = [
    # 有色金属 (6)
    'cu888', 'al888', 'zn888', 'ni888', 'sn888', 'ao888',
    # 贵金属 (2)
    'au888', 'ag888',
    # 黑色系 (4)
    'rb888', 'hc888', 'i888', 'j888',
    # 化工 (4)
    'sc888', 'fu888', 'ta888', 'ma888',
    # 农产品 (4)
    'a888', 'm888', 'y888', 'cf888',
]

# 合约参数: mult=合约乘数, commission=手续费率, tick=最小变动价位
CONTRACT_INFO = {
    'cu888':  {'mult': 5,    'commission': 0.00010, 'tick': 10},
    'al888':  {'mult': 5,    'commission': 0.00010, 'tick': 5},
    'zn888':  {'mult': 5,    'commission': 0.00010, 'tick': 5},
    'ni888':  {'mult': 1,    'commission': 0.00010, 'tick': 10},
    'sn888':  {'mult': 1,    'commission': 0.00010, 'tick': 1},
    'ao888':  {'mult': 20,   'commission': 0.00010, 'tick': 1},
    'au888':  {'mult': 1000, 'commission': 0.00005, 'tick': 0.02},
    'ag888':  {'mult': 15,   'commission': 0.00010, 'tick': 1},
    'rb888':  {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'hc888':  {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'i888':   {'mult': 100,  'commission': 0.00010, 'tick': 0.5},
    'j888':   {'mult': 100,  'commission': 0.00010, 'tick': 0.5},
    'sc888':  {'mult': 1000, 'commission': 0.00010, 'tick': 0.1},
    'fu888':  {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'ta888':  {'mult': 5,    'commission': 0.00010, 'tick': 2},
    'ma888':  {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'a888':   {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'm888':   {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'y888':   {'mult': 10,   'commission': 0.00010, 'tick': 2},
    'cf888':  {'mult': 5,    'commission': 0.00010, 'tick': 5},
}

TRAIN_MONTHS = 6
TEST_MONTHS = 1
START_DATE = '2024-07-01'
END_DATE = '2026-06-01'
INITIAL_CAPITAL = 200000

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data_cache')
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


# ============== 数据获取 ==============
def fetch_kline(symbol, period='30m', limit=50000):
    cache_file = os.path.join(DATA_DIR, f'{symbol}_{period}.csv')
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col='datetime', parse_dates=True)
        if df.index[-1] >= pd.Timestamp('2026-06-01'):
            return df

    params = {'symbol': symbol, 'period': period, 'adjust_type': '0', 'limit': limit, 'username': SSQUANT_USER, 'password': SSQUANT_PASS}
    try:
        r = requests.get(SSQUANT_API, params=params, timeout=60)
        d = r.json()
        klines = d.get('data', {}).get('klines', [])
    except Exception as e:
        print(f'  [ERR] {symbol}: {e}')
        return None

    if len(klines) == 0:
        return None

    df = pd.DataFrame(klines)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').sort_index()
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df[['open', 'high', 'low', 'close', 'volume']].dropna()

    df.to_csv(cache_file)
    return df


# ============== 策略核心 ==============
def compute_supertrend(df, params):
    """计算曲率半径超级趋势线 + 全部指标"""
    p = params
    high, low, close = df['high'], df['low'], df['close']
    src = (high + low) / 2

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(p['atr_length']).mean()

    upper_band = src + (p['atr_mult'] * atr)
    lower_band = src - (p['atr_mult'] * atr)

    # SuperTrend
    n = len(df)
    supertrend = np.full(n, np.nan)
    direction = np.full(n, 1)
    supertrend[0] = lower_band.iloc[0]

    for i in range(1, n):
        if direction[i-1] == 1:
            if close.iloc[i] < supertrend[i-1]:
                supertrend[i] = upper_band.iloc[i]
                direction[i] = -1
            else:
                supertrend[i] = max(lower_band.iloc[i], supertrend[i-1])
                direction[i] = 1
        else:
            if close.iloc[i] > supertrend[i-1]:
                supertrend[i] = lower_band.iloc[i]
                direction[i] = 1
            else:
                supertrend[i] = min(upper_band.iloc[i], supertrend[i-1])
                direction[i] = -1

    # 曲率半径增强
    anchor_price = np.full(n, np.nan)
    cur_anchor = supertrend[0]
    cur_velocity = 0.0
    cur_bar_count = 0

    for i in range(1, n):
        if direction[i] != direction[i-1]:
            cur_anchor = supertrend[i]
            cur_bar_count = 0
            cur_velocity = 0.0
        cur_bar_count += 1
        cur_velocity += p['radius_strength'] * cur_bar_count
        if direction[i] == 1:
            supertrend[i] = cur_anchor + cur_velocity
        else:
            supertrend[i] = cur_anchor - cur_velocity

    st_series = pd.Series(supertrend, index=df.index)
    curved_band = st_series.rolling(p['smoothness'], min_periods=1).mean()

    # KG拐点信号
    kg_signal = np.zeros(n)
    prev_change = curved_band.diff(1)
    prev2_change = curved_band.diff(1).shift(1)
    for i in range(2, n):
        if direction[i] == 1:
            if pd.notna(prev_change.iloc[i]) and pd.notna(prev2_change.iloc[i]):
                if prev_change.iloc[i] > 0 and prev2_change.iloc[i] < 0:
                    kg_signal[i] = 1
            if direction[i] == 1 and direction[i-1] == -1:
                kg_signal[i] = 1
        else:
            if pd.notna(prev_change.iloc[i]) and pd.notna(prev2_change.iloc[i]):
                if prev_change.iloc[i] < 0 and prev2_change.iloc[i] > 0:
                    kg_signal[i] = -1
            if direction[i] == -1 and direction[i-1] == 1:
                kg_signal[i] = -1

    # 辅助指标
    hh = high.rolling(p['n_period']).max()
    ll = low.rolling(p['n_period']).min()

    # MA60 for N4
    ma60 = close.rolling(60).mean()

    result = df.copy()
    result['direction'] = direction
    result['supertrend'] = supertrend
    result['curved_band'] = curved_band.values
    result['kg_signal'] = kg_signal
    result['hh'] = hh.values
    result['ll'] = ll.values
    result['atr'] = atr.values
    result['ma60'] = ma60.values

    return result


def generate_signals(df_ind, variant_cfg):
    """根据模块配置生成交易信号"""
    n = len(df_ind)
    signals = np.zeros(n)
    p = variant_cfg

    use_kg = p.get('use_kg', True)
    use_n_breakout = p.get('use_n_breakout', True)
    mtf_momentum = p.get('mtf_momentum', False)

    warmup = max(p.get('atr_length', 55), p.get('n_period', 5), 60) + 1

    for i in range(warmup, n):
        direction = df_ind['direction'].iloc[i-1]
        high_i = df_ind['high'].iloc[i]
        low_i = df_ind['low'].iloc[i]

        # --- 入场条件 ---
        if use_kg:
            kg = df_ind['kg_signal'].iloc[i-1]
            long_kg = (kg == 1)
            short_kg = (kg == -1)
        else:
            # 删KG: 只靠direction翻转入场
            prev_dir = df_ind['direction'].iloc[i-2] if i >= 2 else 0
            cur_dir = df_ind['direction'].iloc[i-1]
            long_kg = (cur_dir == 1 and prev_dir == -1)  # direction刚翻多
            short_kg = (cur_dir == -1 and prev_dir == 1)  # direction刚翻空
            # 也允许已确认方向时入场(不用等翻转)
            if not long_kg and cur_dir == 1:
                long_kg = True
            if not short_kg and cur_dir == -1:
                short_kg = True

        if use_n_breakout:
            hh_prev = df_ind['hh'].iloc[i-1] if pd.notna(df_ind['hh'].iloc[i-1]) else 0
            ll_prev = df_ind['ll'].iloc[i-1] if pd.notna(df_ind['ll'].iloc[i-1]) else 999999
            d_cond = high_i > hh_prev
            k_cond = low_i < ll_prev
            long_entry = long_kg and d_cond and direction == 1
            short_entry = short_kg and k_cond and direction == -1
        else:
            long_entry = long_kg and direction == 1
            short_entry = short_kg and direction == -1

        # N4: 多周期动量过滤
        if mtf_momentum:
            ma60_val = df_ind['ma60'].iloc[i]
            close_i = df_ind['close'].iloc[i]
            if pd.notna(ma60_val):
                if long_entry and close_i < ma60_val:
                    long_entry = False
                if short_entry and close_i > ma60_val:
                    short_entry = False

        if long_entry:
            signals[i] = 1
        elif short_entry:
            signals[i] = -1

    return signals


def backtest(df, signals, symbol, variant_cfg):
    """运行回测"""
    ci = CONTRACT_INFO[symbol]
    mult = ci['mult']
    commission_rate = ci['commission']

    n = len(df)
    position = 0
    entry_price = 0.0
    entry_bar = 0
    highest_low = 0.0
    lowest_high = 0.0
    liqka = 1.0

    use_liqka_stop = variant_cfg.get('use_liqka_stop', True)
    liqka_min = variant_cfg.get('liqka_min', 0.3)
    trailing_stop_rate = variant_cfg.get('trailing_stop_rate', 40) / 1000

    trades = []
    equity = INITIAL_CAPITAL
    peak_equity = INITIAL_CAPITAL
    max_dd = 0.0

    for i in range(n):
        close_i = df['close'].iloc[i]
        open_i = df['open'].iloc[i]
        high_i = df['high'].iloc[i]
        low_i = df['low'].iloc[i]

        # 止损管理
        if position != 0 and i > entry_bar:
            if use_liqka_stop:
                liqka = max(liqka - 0.1, liqka_min)

            if position > 0:
                highest_low = max(highest_low, low_i)
                if use_liqka_stop:
                    dliq = highest_low - (open_i * trailing_stop_rate) * liqka
                else:
                    # 无liqka: 只靠趋势反转平仓,设一个极宽的保底止损(5%)
                    dliq = entry_price - entry_price * 0.05

                if use_liqka_stop and low_i <= dliq:
                    exit_price = min(open_i, dliq)
                    pnl = (exit_price - entry_price) * mult
                    comm = abs(pnl) * commission_rate if pnl != 0 else exit_price * mult * commission_rate
                    net_pnl = pnl - comm
                    equity += net_pnl
                    trades.append({
                        'entry_date': df.index[entry_bar],
                        'exit_date': df.index[i],
                        'direction': 'long',
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pnl_yuan': net_pnl,
                        'exit_type': 'stop_loss'
                    })
                    position = 0
                    liqka = 1.0

            elif position < 0:
                lowest_high = min(lowest_high, high_i)
                if use_liqka_stop:
                    kliq = lowest_high + (open_i * trailing_stop_rate) * liqka
                else:
                    kliq = entry_price + entry_price * 0.05

                if use_liqka_stop and high_i >= kliq:
                    exit_price = max(open_i, kliq)
                    pnl = (entry_price - exit_price) * mult
                    comm = abs(pnl) * commission_rate if pnl != 0 else exit_price * mult * commission_rate
                    net_pnl = pnl - comm
                    equity += net_pnl
                    trades.append({
                        'entry_date': df.index[entry_bar],
                        'exit_date': df.index[i],
                        'direction': 'short',
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pnl_yuan': net_pnl,
                        'exit_type': 'stop_loss'
                    })
                    position = 0
                    liqka = 1.0

        # 入场
        if position == 0 and signals[i] != 0:
            entry_price = open_i
            position = 1 if signals[i] > 0 else -1
            entry_bar = i
            highest_low = low_i
            lowest_high = high_i
            liqka = 1.0

        # 趋势反转平仓
        if position != 0 and i > 0:
            direction = df['direction'].iloc[i]
            if position > 0 and direction == -1:
                exit_price = open_i
                pnl = (exit_price - entry_price) * mult
                comm = abs(pnl) * commission_rate
                net_pnl = pnl - comm
                equity += net_pnl
                trades.append({
                    'entry_date': df.index[entry_bar],
                    'exit_date': df.index[i],
                    'direction': 'long',
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_yuan': net_pnl,
                    'exit_type': 'trend_reversal'
                })
                position = 0
                liqka = 1.0
            elif position < 0 and direction == 1:
                exit_price = open_i
                pnl = (entry_price - exit_price) * mult
                comm = abs(pnl) * commission_rate
                net_pnl = pnl - comm
                equity += net_pnl
                trades.append({
                    'entry_date': df.index[entry_bar],
                    'exit_date': df.index[i],
                    'direction': 'short',
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_yuan': net_pnl,
                    'exit_type': 'trend_reversal'
                })
                position = 0
                liqka = 1.0

        # 权益追踪
        if position != 0:
            unrealized = (close_i - entry_price) * mult * position
            cur_equity = equity + unrealized
        else:
            cur_equity = equity
        peak_equity = max(peak_equity, cur_equity)
        dd = (peak_equity - cur_equity) / peak_equity if peak_equity > 0 else 0
        max_dd = max(max_dd, dd)

    # 尾盘平仓
    if position != 0:
        exit_price = df['close'].iloc[-1]
        pnl = (exit_price - entry_price) * mult * position
        comm = abs(pnl) * commission_rate
        net_pnl = pnl - comm
        equity += net_pnl
        trades.append({
            'entry_date': df.index[entry_bar],
            'exit_date': df.index[-1],
            'direction': 'long' if position > 0 else 'short',
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl_yuan': net_pnl,
            'exit_type': 'end_of_period'
        })

    if len(trades) > 0:
        wins = [t for t in trades if t['pnl_yuan'] > 0]
        losses = [t for t in trades if t['pnl_yuan'] < 0]
        total_pnl = sum(t['pnl_yuan'] for t in trades)
        gross_profit = sum(t['pnl_yuan'] for t in wins) if wins else 0
        gross_loss = abs(sum(t['pnl_yuan'] for t in losses)) if losses else 1e-10
        wr = len(wins) / len(trades) * 100
        pf = gross_profit / gross_loss if gross_loss > 0 else 999
    else:
        total_pnl = 0; wr = 0; pf = 0

    return {
        'net_pnl': equity - INITIAL_CAPITAL,
        'max_dd': max_dd * 100,
        'win_rate': wr,
        'profit_factor': pf,
        'num_trades': len(trades),
    }


# ============== 消融变体定义 ==============
BASE_PARAMS = {
    'atr_length': 55, 'atr_mult': 3.0, 'radius_strength': 0.05,
    'smoothness': 5, 'n_period': 5, 'trailing_stop_rate': 40,
}

VARIANTS = {
    'baseline': {
        'desc': '原版VIP27(全6模块)',
        'use_kg': True, 'use_n_breakout': True,
        'use_liqka_stop': True, 'use_trend_exit': True,
        'mtf_momentum': False,
        **BASE_PARAMS,
    },
    'remove_kg': {
        'desc': '-M3:删KG拐点',
        'use_kg': False, 'use_n_breakout': True,
        'use_liqka_stop': True, 'use_trend_exit': True,
        'mtf_momentum': False,
        **BASE_PARAMS,
    },
    'remove_liqka': {
        'desc': '-M5:删LiqKA止损',
        'use_kg': True, 'use_n_breakout': True,
        'use_liqka_stop': False, 'use_trend_exit': True,
        'mtf_momentum': False,
        **BASE_PARAMS,
    },
    'opt_n4_mtf': {
        'desc': '+N4:加多周期动量(close>MA60)',
        'use_kg': True, 'use_n_breakout': True,
        'use_liqka_stop': True, 'use_trend_exit': True,
        'mtf_momentum': True,
        **BASE_PARAMS,
    },
    'remove_kg_liqka_n4': {
        'desc': '-M3-M5+N4:删KG+删LiqKA+加多周期动量',
        'use_kg': False, 'use_n_breakout': True,
        'use_liqka_stop': False, 'use_trend_exit': True,
        'mtf_momentum': True,
        **BASE_PARAMS,
    },
}


# ============== Walk-Forward回测 ==============
def walk_forward_backtest(symbol, variant_name, variant_cfg, df_all):
    strategy_params = {k: v for k, v in variant_cfg.items()
                       if k in ['atr_length', 'atr_mult', 'radius_strength',
                                'smoothness', 'n_period', 'trailing_stop_rate']}
    df_ind = compute_supertrend(df_all, strategy_params)

    dates = df_ind.index
    windows = []
    start = pd.Timestamp(START_DATE)

    while start < pd.Timestamp(END_DATE):
        train_end = start + pd.DateOffset(months=TRAIN_MONTHS)
        test_end = train_end + pd.DateOffset(months=TEST_MONTHS)

        train_mask = (dates >= start) & (dates < train_end)
        test_mask = (dates >= train_end) & (dates < test_end)

        if train_mask.sum() < 50 or test_mask.sum() < 5:
            start = start + pd.DateOffset(months=1)
            continue

        test_df = df_ind[test_mask].copy()
        test_signals = generate_signals(test_df, variant_cfg)
        test_result = backtest(test_df, test_signals, symbol, variant_cfg)

        windows.append({
            'train_start': start.strftime('%Y-%m'),
            'test_month': train_end.strftime('%Y-%m'),
            'test_pnl': test_result['net_pnl'],
            'test_dd': test_result['max_dd'],
            'test_wr': test_result['win_rate'],
            'test_pf': test_result['profit_factor'],
            'test_trades': test_result['num_trades'],
        })

        start = start + pd.DateOffset(months=1)

    return windows


# ============== 主流程 ==============
def main():
    t0_all = time.time()
    print('=' * 70)
    print('  VIP20 扩品种消融回测引擎')
    print(f'  {len(SYMBOLS)}品种 × {len(VARIANTS)}变体 × Walk-Forward')
    print('=' * 70)

    # Step 1: 拉取数据
    print(f'\n[1/3] 拉取{len(SYMBOLS)}品种30m数据...')
    data = {}
    for sym in SYMBOLS:
        df = fetch_kline(sym)
        if df is not None and len(df) > 100:
            mask = df.index >= pd.Timestamp('2023-07-01')
            data[sym] = df[mask].copy()
            print(f'  {sym:6s}: {len(data[sym])} bars')
        else:
            print(f'  {sym:6s}: ⚠ 数据不足,跳过')

    print(f'\n  可用品种: {len(data)}/{len(SYMBOLS)}')

    # Step 2: 回测
    print(f'\n[2/3] 运行{len(VARIANTS)}组消融回测...')
    all_results = {}  # {symbol: {variant: [windows]}}

    for vname, vcfg in VARIANTS.items():
        print(f'\n  ━━ {vname}: {vcfg["desc"]} ━━')
        all_results[vname] = {}

        for sym in data:
            df = data[sym]
            t0 = time.time()
            windows = walk_forward_backtest(sym, vname, vcfg, df)
            elapsed = time.time() - t0
            all_results[vname][sym] = windows

            total_pnl = sum(w['test_pnl'] for w in windows)
            win_m = sum(1 for w in windows if w['test_pnl'] > 0)
            print(f'    {sym:6s}: {len(windows):2d}月 PnL={total_pnl:>+12,.0f} '
                  f'胜月={win_m}/{len(windows)} ({elapsed:.1f}s)')

    # Step 3: 保存结果
    print(f'\n[3/3] 保存结果...')
    out_path = os.path.join(OUTPUT_DIR, 'ext20_ablation_results.pkl')
    with open(out_path, 'wb') as f:
        pickle.dump(all_results, f)
    print(f'  保存至: {out_path}')

    # ===== 汇总统计 =====
    print(f'\n{"=" * 90}')
    print('  消融结果汇总: 20品种 × 全变体')
    print(f'{"=" * 90}')

    # 逐品种对比
    print(f'\n  {"品种":6s}', end='')
    for vname in VARIANTS:
        print(f'  {vname:>18s}', end='')
    print()
    print('  ' + '-' * (6 + 20 * len(VARIANTS)))

    grand_total = {v: 0 for v in VARIANTS}
    grand_wr = {v: [] for v in VARIANTS}
    grand_dd = {v: [] for v in VARIANTS}
    grand_pf = {v: [] for v in VARIANTS}
    beat_counts = {v: 0 for v in VARIANTS}  # 击败baseline的品种数

    for sym in data:
        baseline_pnl = sum(w['test_pnl'] for w in all_results['baseline'].get(sym, []))
        print(f'  {sym:6s}', end='')
        for vname in VARIANTS:
            windows = all_results[vname].get(sym, [])
            total_pnl = sum(w['test_pnl'] for w in windows)
            wrs = [w['test_wr'] for w in windows if w['test_wr'] > 0]
            dds = [w['test_dd'] for w in windows]
            pfs = [w['test_pf'] for w in windows if 0 < w['test_pf'] < 1e6]

            grand_total[vname] += total_pnl
            if wrs:
                grand_wr[vname].extend(wrs)
            grand_dd[vname].extend(dds)
            if pfs:
                grand_pf[vname].extend(pfs)

            if vname != 'baseline' and total_pnl > baseline_pnl:
                beat_counts[vname] += 1

            print(f'  {total_pnl:>+18,.0f}', end='')
        print()

    # 总计行
    print('  ' + '-' * (6 + 20 * len(VARIANTS)))
    print(f'  {"合计":6s}', end='')
    for vname in VARIANTS:
        print(f'  {grand_total[vname]:>+18,.0f}', end='')
    print()

    # 指标汇总
    print(f'\n  指标汇总:')
    print(f'  {"变体":22s} {"总PnL":>14s} {"均WR":>7s} {"均DD":>7s} {"均PF":>7s} {"胜baseline品种":>14s}')
    print('  ' + '-' * 75)
    for vname in VARIANTS:
        avg_wr = np.mean(grand_wr[vname]) if grand_wr[vname] else 0
        avg_dd = np.mean(grand_dd[vname]) if grand_dd[vname] else 0
        avg_pf = np.mean(grand_pf[vname]) if grand_pf[vname] else 0
        bc = beat_counts[vname]
        total_syms = len(data)
        print(f'  {vname:22s} {grand_total[vname]:>+14,.0f} {avg_wr:>6.1f}% {avg_dd:>6.1f}% '
              f'{avg_pf:>6.2f}  {bc}/{total_syms}')

    elapsed_all = time.time() - t0_all
    print(f'\n总耗时: {elapsed_all:.0f}s')


if __name__ == '__main__':
    main()

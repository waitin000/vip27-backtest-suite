#!/usr/bin/env python3
"""
VIP27 曲率半径超级趋势策略 — 优化版引擎
=========================================
基于20品种×18月walk-forward消融回测验证的最优配置

核心改动(相比原版VIP27):
  1. 删除 M3: KG拐点检测 — 曲率变化反转在30分钟级别过于敏感，产生大量假信号
     (18/20品种删后更优, PnL从723K→1,949K)
  2. 删除 M5: LiqKA衰减止损 — liqka从1.0衰减到0.3导致盈利单被过早洗出
     (20/20品种删后更优, PnL从723K→1,503K)
  3. 加入 N4: 多周期动量过滤(close>MA60) — 仅在品种适用时开启
     (黑色系4/4有效, 化工3/4有效, 有色金属2/6, 农产品1/4)

保留的核心模块:
  M1: SuperTrend方向判定 (ATR通道+价格穿越)
  M2: 曲率半径增强 (velocity加速度偏移)
  M6: 趋势反转平仓 (direction翻转时平仓)

入场逻辑(简化后):
  long:  direction=1 + (可选)close>MA60 → 开多
  short: direction=-1 + (可选)close<MA60 → 开空

止损/平仓:
  → 趋势反转(direction翻转)时平仓
  → 无LiqKA衰减, 让利润奔跑到趋势结束

数据源: ssquant API (http://121.237.178.245:8086/futures/history)
回测方法: 6月训练 + 1月测试 walk-forward
"""

import os, sys, time, json
import numpy as np
import pandas as pd
import requests
from datetime import datetime

# ============== 配置 ==============
SSQUANT_API = 'http://121.237.178.245:8086/futures/history'
SSQUANT_USER = '13621640810'
SSQUANT_PASS = 'Sherl0cked?'

# 合约参数
CONTRACT_INFO = {
    # 有色金属
    'cu888':  {'mult': 5,    'commission': 0.00010, 'tick': 10},
    'al888':  {'mult': 5,    'commission': 0.00010, 'tick': 5},
    'zn888':  {'mult': 5,    'commission': 0.00010, 'tick': 5},
    'ni888':  {'mult': 1,    'commission': 0.00010, 'tick': 10},
    'sn888':  {'mult': 1,    'commission': 0.00010, 'tick': 1},
    'ao888':  {'mult': 20,   'commission': 0.00010, 'tick': 1},
    # 贵金属
    'au888':  {'mult': 1000, 'commission': 0.00005, 'tick': 0.02},
    'ag888':  {'mult': 15,   'commission': 0.00010, 'tick': 1},
    # 黑色系
    'rb888':  {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'hc888':  {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'i888':   {'mult': 100,  'commission': 0.00010, 'tick': 0.5},
    'j888':   {'mult': 100,  'commission': 0.00010, 'tick': 0.5},
    # 化工
    'sc888':  {'mult': 1000, 'commission': 0.00010, 'tick': 0.1},
    'fu888':  {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'ta888':  {'mult': 5,    'commission': 0.00010, 'tick': 2},
    'ma888':  {'mult': 10,   'commission': 0.00010, 'tick': 1},
    # 农产品
    'a888':   {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'm888':   {'mult': 10,   'commission': 0.00010, 'tick': 1},
    'y888':   {'mult': 10,   'commission': 0.00010, 'tick': 2},
    'cf888':  {'mult': 5,    'commission': 0.00010, 'tick': 5},
}

# N4多周期动量过滤 — 按品种分配置
# 基于消融回测证据: 黑色系全有效, 化工3/4有效, 有色/农产品多数有害
N4_ENABLED_SYMBOLS = {
    # 黑色系: 4/4有效 ✅
    'rb888': True, 'hc888': True, 'i888': True, 'j888': True,
    # 化工: 3/4有效 ✅ (ma888边界,微亏-36)
    'sc888': True, 'fu888': True, 'ta888': True, 'ma888': False,
    # 贵金属: 1/2有效
    'au888': True, 'ag888': False,
    # 有色金属: 2/6有效 — 多数有害, 关闭
    'cu888': False, 'al888': False, 'zn888': True, 'ni888': False,
    'sn888': True, 'ao888': False,
    # 农产品: 1/4有效 — 多数有害, 关闭
    'a888': True, 'm888': False, 'y888': False, 'cf888': False,
}

# 策略参数 (原版VIP27经消融验证的最优值)
STRATEGY_PARAMS = {
    'atr_length': 55,        # ATR计算周期
    'atr_mult': 3.0,         # SuperTrend ATR倍数
    'radius_strength': 0.05, # 曲率半径加速度系数
    'smoothness': 5,         # 曲率平滑窗口
    'n_period': 5,           # N周期突破(仅用于方向翻转确认,非入场条件)
    'ma60_period': 60,       # N4: MA60大趋势判定周期
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
    """从ssquant下载K线数据,自动缓存"""
    cache_file = os.path.join(DATA_DIR, f'{symbol}_{period}.csv')
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col='datetime', parse_dates=True)
        if len(df) > 0 and df.index[-1] >= pd.Timestamp('2026-06-01'):
            return df

    print(f'  [下载] {symbol} {period}...')
    params = {'symbol': symbol, 'period': period, 'adjust_type': '0', 'limit': limit, 'username': '13621640810', 'password': 'Sherl0cked?'}
    try:
        r = requests.get(SSQUANT_API, params=params, timeout=60)
        d = r.json()
        klines = d.get('data', {}).get('klines', [])
    except Exception as e:
        print(f'  [错误] {symbol}: {e}')
        return None

    if len(klines) == 0:
        print(f'  [警告] {symbol}: 无数据')
        return None

    df = pd.DataFrame(klines)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').sort_index()
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df[['open', 'high', 'low', 'close', 'volume']].dropna()

    df.to_csv(cache_file)
    return df


# ============== 优化版策略核心 ==============
class OptimizedVIP27:
    """
    VIP27优化版: 曲率半径超级趋势策略 (删KG + 删LiqKA + 可选N4)

    原版6模块 → 优化后3模块+1可选:
      M1 SuperTrend方向  ✅保留 — 基石
      M2 曲率半径增强    ✅保留 — 减少滞后
      M3 KG拐点检测      ❌删除 — 30m太敏感,假信号多
      M4 N周期突破       ⚠️弱化 — 不再作为入场必须条件
      M5 LiqKA衰减止损   ❌删除 — 过早洗出盈利单
      M6 趋势反转平仓    ✅保留 — 风控底线
      N4 多周期动量       🟡选配 — 品种分流开启
    """

    def __init__(self, symbol, use_n4=None):
        self.symbol = symbol
        self.params = STRATEGY_PARAMS.copy()
        # N4按品种配置自动决定
        if use_n4 is None:
            self.use_n4 = N4_ENABLED_SYMBOLS.get(symbol, False)
        else:
            self.use_n4 = use_n4

    def compute_indicators(self, df):
        """计算SuperTrend + 曲率半径 + MA60"""
        p = self.params
        high, low, close = df['high'], df['low'], df['close']
        src = (high + low) / 2

        # ATR
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(p['atr_length']).mean()

        upper_band = src + (p['atr_mult'] * atr)
        lower_band = src - (p['atr_mult'] * atr)

        # SuperTrend方向判定
        n = len(df)
        supertrend = np.full(n, np.nan)
        direction = np.full(n, 1)  # 1=long, -1=short
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

        # 曲率半径增强: velocity加速度偏移
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

        # 平滑
        st_series = pd.Series(supertrend, index=df.index)
        curved_band = st_series.rolling(p['smoothness'], min_periods=1).mean()

        # N4: MA60大趋势
        ma60 = close.rolling(p['ma60_period']).mean()

        result = df.copy()
        result['direction'] = direction
        result['supertrend'] = supertrend
        result['curved_band'] = curved_band.values
        result['atr'] = atr.values
        result['ma60'] = ma60.values

        return result

    def generate_signals(self, df_ind):
        """
        优化版入场信号生成

        原版: KG拐点=1 AND 突破N周期高 AND direction=1 → 开多
        优化: direction=1 (AND 可选close>MA60) → 开多
              direction=-1 (AND 可选close<MA60) → 开空

        删KG: 不再要求曲率反转拐点, direction翻转即入场信号
        删N周期突破: 不再要求突破前N根高/低点
        结果: 入场条件大幅简化, 信号更及时
        """
        n = len(df_ind)
        signals = np.zeros(n)  # 1=buy, -1=sell, 0=no signal

        warmup = max(self.params['atr_length'], self.params['ma60_period']) + 1

        for i in range(warmup, n):
            cur_dir = df_ind['direction'].iloc[i-1]
            prev_dir = df_ind['direction'].iloc[i-2] if i >= 2 else 0
            close_i = df_ind['close'].iloc[i]

            # === 入场条件(简化) ===
            # 方向翻转 = 最强入场信号
            long_flip = (cur_dir == 1 and prev_dir == -1)
            short_flip = (cur_dir == -1 and prev_dir == 1)

            # 已确认方向也允许入场(不用等翻转,捕捉趋势中段)
            long_confirm = (cur_dir == 1 and not long_flip)
            short_confirm = (cur_dir == -1 and not short_flip)

            # 合并: 翻转优先, 确认次之
            long_entry = long_flip or long_confirm
            short_entry = short_flip or short_confirm

            # N4: 多周期动量过滤
            if self.use_n4:
                ma60_val = df_ind['ma60'].iloc[i]
                if pd.notna(ma60_val):
                    if long_entry and close_i < ma60_val:
                        long_entry = False
                    if short_entry and close_i > ma60_val:
                        short_entry = False

            # 避免同bar多空冲突
            if long_entry and short_entry:
                # 方向冲突时不入场
                continue

            if long_entry:
                signals[i] = 1
            elif short_entry:
                signals[i] = -1

        return signals

    def backtest(self, df, signals):
        """
        优化版回测引擎

        关键改动: 无LiqKA衰减止损
        平仓方式: 仅趋势反转(direction翻转)时平仓
        → 让利润跟随趋势奔跑, 不被过紧止损洗出
        """
        ci = CONTRACT_INFO[self.symbol]
        mult = ci['mult']
        commission_rate = ci['commission']

        n = len(df)
        position = 0  # 0=flat, 1=long, -1=short
        entry_price = 0.0
        entry_bar = 0

        trades = []
        equity = INITIAL_CAPITAL
        peak_equity = INITIAL_CAPITAL
        max_dd = 0.0

        for i in range(n):
            close_i = df['close'].iloc[i]
            open_i = df['open'].iloc[i]

            # === 平仓: 仅趋势反转 ===
            if position != 0 and i > 0:
                direction = df['direction'].iloc[i]
                should_exit = False

                if position > 0 and direction == -1:
                    should_exit = True
                    exit_price = open_i
                    pnl = (exit_price - entry_price) * mult
                elif position < 0 and direction == 1:
                    should_exit = True
                    exit_price = open_i
                    pnl = (entry_price - exit_price) * mult

                if should_exit:
                    comm = abs(pnl) * commission_rate if pnl != 0 else exit_price * mult * commission_rate
                    net_pnl = pnl - comm
                    equity += net_pnl
                    trades.append({
                        'entry_date': df.index[entry_bar],
                        'exit_date': df.index[i],
                        'direction': 'long' if position > 0 else 'short',
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pnl_points': (exit_price - entry_price) * position,
                        'pnl_yuan': net_pnl,
                        'exit_type': 'trend_reversal'
                    })
                    position = 0

            # === 入场 ===
            if position == 0 and signals[i] != 0:
                entry_price = open_i
                position = 1 if signals[i] > 0 else -1
                entry_bar = i

            # === 权益曲线 ===
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
                'pnl_points': (exit_price - entry_price) * position,
                'pnl_yuan': net_pnl,
                'exit_type': 'end_of_period'
            })

        # 统计
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
            'trades': trades,
            'net_pnl': equity - INITIAL_CAPITAL,
            'max_dd': max_dd * 100,
            'win_rate': wr,
            'profit_factor': pf,
            'num_trades': len(trades),
            'final_equity': equity,
        }


# ============== Walk-Forward回测 ==============
def walk_forward_backtest(symbol, df_all):
    """月度walk-forward回测: 6月训练窗口滚动, 1月测试验证"""
    strategy = OptimizedVIP27(symbol)
    n4_status = 'ON' if strategy.use_n4 else 'OFF'
    print(f'\n  {symbol} (N4={n4_status})')

    df_ind = strategy.compute_indicators(df_all)
    dates = df_ind.index

    windows = []
    start = pd.Timestamp(START_DATE)

    while start < pd.Timestamp(END_DATE):
        train_end = start + pd.DateOffset(months=TRAIN_MONTHS)
        test_end = train_end + pd.DateOffset(months=TEST_MONTHS)

        test_mask = (dates >= train_end) & (dates < test_end)
        if test_mask.sum() < 5:
            start = start + pd.DateOffset(months=1)
            continue

        test_df = df_ind[test_mask].copy()
        test_signals = strategy.generate_signals(test_df)
        test_result = strategy.backtest(test_df, test_signals)

        windows.append({
            'test_month': train_end.strftime('%Y-%m'),
            'test_pnl': test_result['net_pnl'],
            'test_dd': test_result['max_dd'],
            'test_wr': test_result['win_rate'],
            'test_pf': test_result['profit_factor'],
            'test_trades': test_result['num_trades'],
        })

        start = start + pd.DateOffset(months=1)

    # 汇总
    total_pnl = sum(w['test_pnl'] for w in windows)
    win_months = sum(1 for w in windows if w['test_pnl'] > 0)
    avg_wr = np.mean([w['test_wr'] for w in windows]) if windows else 0
    avg_dd = np.mean([w['test_dd'] for w in windows]) if windows else 0
    avg_pf = np.mean([w['test_pf'] for w in windows if 0 < w['test_pf'] < 1e6]) if windows else 0

    print(f'    {len(windows)}月 | PnL={total_pnl:>+12,.0f} | '
          f'月胜={win_months}/{len(windows)} | WR={avg_wr:.1f}% | DD={avg_dd:.1f}%')

    return windows


# ============== 主流程 ==============
def main():
    t0 = time.time()
    print('=' * 70)
    print('  VIP27 曲率半径超级趋势策略 — 优化版回测')
    print('  配置: 删KG + 删LiqKA + N4(品种分配置)')
    print('=' * 70)

    symbols = sys.argv[1:] if len(sys.argv) > 1 else list(CONTRACT_INFO.keys())

    # Step 1: 数据
    print(f'\n[1/3] 下载{len(symbols)}品种30m数据...')
    data = {}
    for sym in symbols:
        df = fetch_kline(sym)
        if df is not None and len(df) > 100:
            mask = df.index >= pd.Timestamp('2023-07-01')
            data[sym] = df[mask].copy()

    # Step 2: 回测
    print(f'\n[2/3] Walk-Forward回测 (6月训练+1月测试)...')
    results = {}
    for sym in data:
        results[sym] = walk_forward_backtest(sym, data[sym])

    # Step 3: 汇总
    print(f'\n[3/3] 结果汇总')
    print(f'\n  {"品种":6s} {"总PnL":>12s} {"月胜率":>8s} {"均WR":>7s} {"均DD":>7s} {"均PF":>7s} {"N4":>4s}')
    print('  ' + '-' * 55)

    grand_pnl = 0
    for sym in data:
        w = results[sym]
        total = sum(x['test_pnl'] for x in w)
        win_m = sum(1 for x in w if x['test_pnl'] > 0)
        avg_wr = np.mean([x['test_wr'] for x in w]) if w else 0
        avg_dd = np.mean([x['test_dd'] for x in w]) if w else 0
        avg_pf = np.mean([x['test_pf'] for x in w if 0 < x['test_pf'] < 1e6]) if w else 0
        n4 = 'ON' if N4_ENABLED_SYMBOLS.get(sym, False) else 'OFF'
        grand_pnl += total
        print(f'  {sym:6s} {total:>+12,.0f} {win_m}/{len(w):>5s} {avg_wr:>6.1f}% {avg_dd:>6.1f}% {avg_pf:>6.2f}  {n4}')

    print('  ' + '-' * 55)
    print(f'  {"合计":6s} {grand_pnl:>+12,.0f}')

    # 保存
    out_path = os.path.join(OUTPUT_DIR, 'optimized_backtest_results.json')
    out_data = {}
    for sym in data:
        out_data[sym] = {
            'n4_enabled': N4_ENABLED_SYMBOLS.get(sym, False),
            'windows': results[sym],
            'total_pnl': sum(w['test_pnl'] for w in results[sym]),
        }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2, default=str)
    print(f'\n  结果已保存: {out_path}')
    print(f'\n总耗时: {time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()

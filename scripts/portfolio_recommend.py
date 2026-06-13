"""Smart portfolio recommendation - 5 symbols, margin <= 200K"""
import pickle, zipfile, numpy as np
from itertools import combinations

z = zipfile.ZipFile('C:/Users/boris/Desktop/VIP27_optimized.ZIP')
data = pickle.load(z.open('backtest_results_ext/ext20_ablation_results.pkl'))
opt = 'remove_kg_liqka_n4'

name_map = {
    'a888':'豆一','ag888':'白银','al888':'铝','ao888':'氧化铝',
    'au888':'黄金','cf888':'棉花','cu888':'铜','fu888':'燃油',
    'hc888':'热卷','i888':'铁矿','j888':'焦炭','m888':'豆粕',
    'ma888':'甲醇','ni888':'镍','rb888':'螺纹','sc888':'原油',
    'sn888':'锡','ta888':'PTA','y888':'豆油','zn888':'锌'
}
board_map = {
    'a888':'DCE','ag888':'SHFE','al888':'SHFE','ao888':'SHFE',
    'au888':'SHFE','cf888':'CZCE','cu888':'SHFE','fu888':'SHFE',
    'hc888':'SHFE','i888':'DCE','j888':'DCE','m888':'DCE',
    'ma888':'CZCE','ni888':'SHFE','rb888':'SHFE','sc888':'INE',
    'sn888':'SHFE','ta888':'CZCE','y888':'DCE','zn888':'SHFE'
}

margin_est = {
    'a888':4200, 'ag888':14400, 'al888':10250, 'ao888':7600,
    'au888':62000, 'cf888':8000, 'cu888':46800, 'fu888':4200,
    'hc888':3800, 'i888':9960, 'j888':30750, 'm888':3000,
    'ma888':2300, 'ni888':15600, 'rb888':3800, 'sc888':63600,
    'sn888':34800, 'ta888':2950, 'y888':8000, 'zn888':12500
}

symbols = sorted(data['baseline'].keys())
all_months = 18

# Get per-symbol per-month data
sym_pnls = {}
for sym in symbols:
    opt_pnls = []
    for w in data[opt][sym]:
        opt_pnls.append(float(w['test_pnl']))
    sym_pnls[sym] = np.array(opt_pnls)

# For each combo compute combined metrics
MAX_MARGIN = 200000
results = []

for combo in combinations(symbols, 5):
    margin = sum(margin_est[s] for s in combo)
    if margin > MAX_MARGIN: continue
    
    # Combined monthly PnL (equal weight, 1 lot each)
    combo_pnls = sum(sym_pnls[s] for s in combo)
    total_pnl = np.sum(combo_pnls)
    avg_month = np.mean(combo_pnls)
    std = np.std(combo_pnls)
    sharpe = avg_month / std if std > 0 else 0
    
    # Max drawdown
    cum = np.cumsum(combo_pnls)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak * 100
    max_dd = abs(np.min(dd))
    
    # Win rate
    win_months = np.sum(combo_pnls > 0)
    win_rate = win_months / len(combo_pnls)
    
    # Diversification score: number of exchanges covered
    exchanges = set(board_map[s] for s in combo)
    div_score = len(exchanges)
    
    results.append({
        'symbols': combo,
        'margin': margin,
        'total_pnl': total_pnl,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'win_rate': win_rate,
        'avg_month': avg_month,
        'std': std,
        'div_score': div_score,
    })

# Sort by different criteria
print("=" * 110)
print("20万保证金 5品种组合推荐")
print("=" * 110)

# Strategy 1: Max total PnL
by_pnl = sorted(results, key=lambda x: x['total_pnl'], reverse=True)
print("\n【方案一】按总收益最大排序")
print(f"{'Rank':>4} {'组合':>35} {'保证金':>10} {'总PnL':>12} {'月Sharpe':>9} {'最大回撤':>9} {'月胜率':>7} {'交易所':>6}")
print("-" * 90)
for i, r in enumerate(by_pnl[:10]):
    names = ' '.join(name_map[s] for s in r['symbols'])
    exs = '/'.join(sorted(set(board_map[s] for s in r['symbols'])))
    print(f"  {i+1:>2} {names:>30} {r['margin']:>8,.0f} {r['total_pnl']:>+10,.0f} {r['sharpe']:>7.2f} {r['max_dd']:>7.1f}% {r['win_rate']*100:>5.0f}% {exs:>6}")

# Strategy 2: Max Sharpe
by_sharpe = sorted(results, key=lambda x: x['sharpe'], reverse=True)
print("\n【方案二】按夏普比率最大排序（风险调整后最优）")
print(f"{'Rank':>4} {'组合':>35} {'保证金':>10} {'总PnL':>12} {'月Sharpe':>9} {'最大回撤':>9} {'月胜率':>7} {'交易所':>6}")
print("-" * 90)
for i, r in enumerate(by_sharpe[:10]):
    names = ' '.join(name_map[s] for s in r['symbols'])
    exs = '/'.join(sorted(set(board_map[s] for s in r['symbols'])))
    print(f"  {i+1:>2} {names:>30} {r['margin']:>8,.0f} {r['total_pnl']:>+10,.0f} {r['sharpe']:>7.2f} {r['max_dd']:>7.1f}% {r['win_rate']*100:>5.0f}% {exs:>6}")

# Strategy 3: Best Sharpe with PnL > 200K (pragmatic)
by_pragmatic = sorted([r for r in results if r['total_pnl'] > 200000 and r['margin'] <= 180000], 
                      key=lambda x: x['sharpe'] * x['total_pnl'] / x['margin'], reverse=True)
print("\n【方案三】收益风险平衡（收益>20万 + 夏普>1 + 保证金适中）")
print(f"{'Rank':>4} {'组合':>35} {'保证金':>10} {'总PnL':>12} {'月Sharpe':>9} {'最大回撤':>9} {'月胜率':>7} {'交易所':>6}")
print("-" * 90)
for i, r in enumerate(by_pragmatic[:10]):
    names = ' '.join(name_map[s] for s in r['symbols'])
    exs = '/'.join(sorted(set(board_map[s] for s in r['symbols'])))
    print(f"  {i+1:>2} {names:>30} {r['margin']:>8,.0f} {r['total_pnl']:>+10,.0f} {r['sharpe']:>7.2f} {r['max_dd']:>7.1f}% {r['win_rate']*100:>5.0f}% {exs:>6}")

# Highlight specific recommended combos
print("\n\n【推荐方案对比】")
print(f"{'方案':>20} {'品种':>42} {'保证金':>10} {'总PnL':>12} {'月Sharpe':>9} {'最大回撤':>9} {'月胜率':>7}")
print("-" * 110)

# Find specific good combos
candidates = [
    ('保守-量化', ['a888','hc888','m888','ma888','y888']),
    ('均衡-黑色系', ['a888','hc888','i888','j888','ma888']),
    ('均衡-DCE系', ['a888','i888','j888','m888','y888']),
    ('积极-贵金属系', ['ag888','ao888','au888','ni888','sn888']),
    ('积极-有色系', ['al888','ao888','cu888','ni888','sn888']),
    ('全明星组合', ['a888','j888','ao888','ag888','i888']),
]

for label, syms in candidates:
    margin = sum(margin_est[s] for s in syms)
    if margin > MAX_MARGIN:
        continue
    combo_pnls = sum(sym_pnls[s] for s in syms)
    total_pnl = np.sum(combo_pnls)
    avg = np.mean(combo_pnls)
    std = np.std(combo_pnls)
    sharpe = avg / std if std > 0 else 0
    cum = np.cumsum(combo_pnls)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak * 100
    max_dd = abs(np.min(dd))
    win_rate = np.sum(combo_pnls > 0) / len(combo_pnls)
    names = ' '.join(name_map[s] for s in syms)
    print(f"  {label:>20} {names:>42} {margin:>8,.0f} {total_pnl:>+10,.0f} {sharpe:>7.2f} {max_dd:>7.1f}% {win_rate*100:>5.0f}%")

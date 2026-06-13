import pickle, zipfile, numpy as np
z = zipfile.ZipFile('C:/Users/boris/Desktop/VIP27_optimized.ZIP')
data = pickle.load(z.open('backtest_results_ext/ext20_ablation_results.pkl'))
opt = 'remove_kg_liqka_n4'
symbols = ['a888','hc888','i888','j888','ma888']
all_months = sorted(set(w['test_month'] for w in data[opt][symbols[0]]))
combo = []
for i in range(len(all_months)):
    s = sum(float(data[opt][sym][i]['test_pnl']) for sym in symbols)
    combo.append(s)
arr = np.array(combo)
avg = np.mean(arr)
std = np.std(arr)
sharpe = avg / std if std > 0 else 0
cum = np.cumsum(arr)
peak = np.maximum.accumulate(cum)
dd = (cum - peak) / peak * 100
max_dd = abs(np.min(dd))
calmar = np.sum(arr) / max_dd if max_dd > 0 else 0
print('=== 5品种组合 各1手 (walk-forward) ===')
print(f'总PnL: {np.sum(arr):+,.0f}')
print(f'月均PnL: {avg:+,.0f}')
print(f'月PnL标准差: {std:+,.0f}')
print(f'月Sharpe: {sharpe:.3f}')
print(f'年化Sharpe: {sharpe * np.sqrt(12):.3f}')
print(f'最大回撤: {max_dd:.2f}%')
print(f'Calmar比: {calmar:.2f}')
print(f'胜月: {np.sum(arr>0)}/{len(arr)} ({np.sum(arr>0)/len(arr)*100:.0f}%)')
print()
print(f'{"月份":>8} {"PnL":>10} {"累计":>10} {"回撤":>8}')
for i, m in enumerate(all_months):
    print(f'  {m:>8} {combo[i]:>+9,.0f} {cum[i]:>+9,.0f} {dd[i]:>+7.1f}%')
print(f'\n最大回撤发生在: {all_months[np.argmin(dd)]}')

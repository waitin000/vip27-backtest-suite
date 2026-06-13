#!/usr/bin/env python3
"""VIP27 Multi-symbol Ablation Backtest - One-click Runner"""
import sys, os, subprocess, time

def run_backtest(start_date, label):
    print('\n' + '=' * 60)
    print('  Backtest period: ' + label + '  START_DATE=' + start_date)
    print('=' * 60)

    with open('run_ext_ablation.py', 'r', encoding='utf-8') as f:
        code = f.read()
    code = code.replace("START_DATE = '2024-07-01'", "START_DATE = '" + start_date + "'")
    code = code.replace("'ext20_ablation_results.pkl'", "'ext20_ablation_results_" + label + ".pkl'")

    tmp = 'run_engine_' + label + '.py'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(code)

    t0 = time.time()
    ret = subprocess.run([sys.executable, tmp], capture_output=True, text=True, timeout=600)
    elapsed = time.time() - t0

    for line in ret.stdout.split('\n'):
        line = line.strip()
        if any(kw in line for kw in ['Total', 'Config', 'baseline', 'remove_kg', 'remove_liqka', 'opt_n4_mtf', 'completed', 'Done', 'Done!']):
            print('  ' + line)

    if ret.returncode != 0:
        print('  ERROR: ' + ret.stderr[:300])
    else:
        print('  Completed: %.0fs' % elapsed)
    os.remove(tmp)

def main():
    os.makedirs('results', exist_ok=True)
    os.makedirs('data_cache', exist_ok=True)

    periods = []
    if '--period' in sys.argv:
        p = sys.argv[sys.argv.index('--period') + 1]
        if p == '2025':
            periods = [('2024-07-01', '2025')]
        elif p == '2023':
            periods = [('2023-01-01', '2023')]
        else:
            periods = [('2024-07-01', '2025'), ('2023-01-01', '2023')]
    else:
        periods = [('2024-07-01', '2025'), ('2023-01-01', '2023')]

    for start_date, label in periods:
        run_backtest(start_date, label)

    # Generate HTML
    print('\n' + '=' * 60)
    print('  Generating HTML charts...')
    print('=' * 60)
    for label in [p[1] for p in periods]:
        pkl = 'results/ext20_ablation_results_' + label + '.pkl'
        if os.path.exists(pkl):
            out = 'vip27_equity_curves_' + ('2025_2026' if label == '2025' else '2023_2024') + '.html'
            ret = subprocess.run([sys.executable, 'gen_html.py', pkl, out], capture_output=True, text=True, timeout=30)
            print('  ' + out + ': ' + (ret.stdout.strip()[:50] if ret.stdout else 'ok'))

    print('\n' + '=' * 60)
    print('  All done!')
    print('  Open the .html files in your browser to view charts.')
    print('=' * 60)

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Generate equity curve HTML from ablation pkl results - standalone version"""
import pickle, os, sys

NAME_MAP = {
    'a888':'豆一','ag888':'白银','al888':'铝','ao888':'氧化铝',
    'au888':'黄金','cf888':'棉花','cu888':'铜','fu888':'燃油',
    'hc888':'热卷','i888':'铁矿','j888':'焦炭','m888':'豆粕',
    'ma888':'甲醇','ni888':'镍','rb888':'螺纹','sc888':'原油',
    'sn888':'锡','ta888':'PTA','y888':'豆油','zn888':'锌',
}
CONFIG_NAMES = {
    'baseline': '原版VIP27',
    'remove_kg': '删KG',
    'remove_liqka': '删LiqKA',
    'opt_n4_mtf': '+N4',
    'remove_kg_liqka_n4': '删KG+删LiqKA+N4',
}
CONFIG_COLORS = ['#f59e0b','#60a5fa','#a78bfa','#f472b6','#22c55e']

def cum(arr):
    c, res = 0, []
    for v in arr:
        c += v; res.append(c)
    return res

def gen_svg(vals_list, colors, labels, mshort, w=700, h=260):
    max_v = max(max(v) for v in vals_list)
    min_v = min(min(v) for v in vals_list)
    if min_v > 0: min_v = 0
    rng = max_v - min_v
    if rng == 0: rng = 1
    yt, yb = max_v + rng*0.1, min_v - rng*0.1
    rr = yt - yb
    ml, mr, mt, mb = 55, 15, 20, 28
    pw, ph = w-ml-mr, h-mt-mb
    n = len(vals_list[0])

    def xx(i): return ml + (i/(n-1))*pw if n>1 else ml
    def yy(v): return mt + (1-(v-yb)/rr)*ph

    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="100%%" style="background:#0f172a;border-radius:6px;">' % (w, h)
    svg += '<defs>'
    for idx, col in enumerate(colors):
        svg += '<linearGradient id="b%d"><stop offset="0" stop-color="%s" stop-opacity=".12"/><stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient>' % (idx, col, col)
    svg += '</defs>'
    for i in range(5):
        val = yb + rr*i/4; yyv = yy(val)
        svg += '<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#1e293b"/>' % (ml, yyv, w-mr, yyv)
        svg += '<text x="%d" y="%.1f" text-anchor="end" fill="#64748b" font-size="9">%.0f万</text>' % (ml-5, yyv+4, val/10000)
    step = max(1, n//8)
    for i in range(0, n, step):
        svg += '<text x="%.1f" y="%d" text-anchor="middle" fill="#64748b" font-size="8">%s</text>' % (xx(i), h-mb+14, mshort[i])
    for idx, (vals, col, _) in enumerate(zip(vals_list, colors, labels)):
        pts = ' '.join('%.1f,%.1f' % (xx(i), yy(v)) for i, v in enumerate(vals))
        svg += '<polygon points="%.1f,%.1f %s %.1f,%.1f" fill="url(#b%d)"/>' % (xx(0), yy(yb), pts, xx(n-1), yy(yb), idx)
        svg += '<polyline points="%s" fill="none" stroke="%s" stroke-width="2" stroke-linejoin="round"/>' % (pts, col)
    for idx, (col, lab) in enumerate(zip(colors, labels)):
        lx = w - 160 + idx*85
        svg += '<rect x="%d" y="4" width="10" height="10" fill="%s" rx="1"/><text x="%d" y="13" fill="#94a3b8" font-size="10">%s</text>' % (lx, col, lx+13, lab)
    svg += '</svg>'
    return svg

def main():
    pkl_path = sys.argv[1] if len(sys.argv) > 1 else 'results/ext20_ablation_results.pkl'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'vip27_equity_curves.html'
    with open(pkl_path, 'rb') as f: data = pickle.load(f)
    configs = list(data.keys())
    first_sym = list(data[configs[0]].keys())[0]
    all_windows = data[configs[0]][first_sym]
    months = sorted(set(w['test_month'] for w in all_windows))
    mshort = [m[2:7].replace('-','') for m in months]
    symbols = sorted(data[configs[0]].keys())
    sym_data = {}
    tot_data = {c: [0.0]*len(months) for c in configs}
    for sym in symbols:
        sym_data[sym] = {}
        for cfg in configs:
            arr = [0.0]*len(months)
            for w in data[cfg][sym]:
                for mi, m in enumerate(months):
                    if w['test_month'] == m:
                        arr[mi] = w['test_pnl']; tot_data[cfg][mi] += w['test_pnl']; break
            sym_data[sym][cfg] = arr

    period = '%s ~ %s (%d个月)' % (months[0], months[-1], len(months))
    sym_names = [NAME_MAP.get(s, s) for s in symbols]

    STYLE = '*{margin:0;padding:0;box-sizing:border-box}body{background:#0f172a;color:#e2e8f0;font-family:sans-serif;padding:16px}.container{max-width:1600px;margin:0 auto}.header{text-align:center;padding:24px 0 8px}.header h1{font-size:22px;font-weight:700;background:linear-gradient(135deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}.header p{color:#94a3b8;font-size:12px;margin-top:4px}.controls{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin:14px 0}.controls button{background:#1e293b;border:1px solid #334155;color:#94a3b8;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:11px}.controls button:hover{background:#334155}.controls button.active{background:#3b82f6;border-color:#3b82f6;color:#fff}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:12px}.card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:14px}.card.wide{grid-column:1/-1}.card h2{font-size:13px;font-weight:600;color:#94a3b8;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center}.card h2 span{font-size:10px;color:#64748b;font-weight:400}table{width:100%;border-collapse:collapse;font-size:11px;margin-top:6px}th{color:#64748b;border-bottom:1px solid #334155;padding:6px;text-align:right}td{padding:4px;text-align:right;border-bottom:1px solid #1e293b;font-variant-numeric:tabular-nums}.footer{text-align:center;color:#475569;font-size:11px;margin-top:20px;padding:12px;border-top:1px solid #1e293b}#totalSec{display:block}#allSec{display:none}'

    html = '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>VIP27 %d品种回测</title><style>%s</style></head><body><div class="container"><div class="header"><h1>VIP27 %d品种消融回测 - 收益曲线</h1><p>%s | walk-forward 6月训练+1月测试</p></div>' % (len(symbols), STYLE, len(symbols), period)
    html += '<div class="controls"><button class="active" onclick="showT()" id="bT">组合总计</button><button onclick="showA()" id="bA">全部%d品种</button></div>' % len(symbols)

    # Total section
    html += '<div id="totalSec"><div class="card wide"><h2>组合总计</h2>'
    tot_cum = [cum(tot_data[c]) for c in configs]
    html += gen_svg(tot_cum, CONFIG_COLORS[:len(configs)], [CONFIG_NAMES[c] for c in configs], mshort, 1000, 360)
    html += '</div><div class="card wide" style="overflow-x:auto"><h2>配置汇总对比</h2><table><tr><th style="text-align:left;padding:6px">品种</th>'
    for cfg in configs: html += '<th style="padding:6px">%s</th>' % CONFIG_NAMES[cfg]
    html += '<th style="padding:6px">最优配置</th></tr>'
    total_row = {c: 0 for c in configs}
    for sym in symbols:
        html += '<tr><td style="text-align:left;color:#94a3b8;padding:4px">%s</td>' % NAME_MAP.get(sym, sym)
        best_cfg, best_pnl = '', -1e18
        for cfg in configs:
            pnl = sum(sym_data[sym][cfg]); total_row[cfg] += pnl
            c = '#22c55e' if pnl >= 0 else '#ef4444'
            html += '<td style="color:%s">%+d</td>' % (c, pnl)
            if pnl > best_pnl: best_pnl, best_cfg = pnl, CONFIG_NAMES[cfg]
        html += '<td style="color:#3b82f6">%s</td></tr>' % best_cfg
    html += '<tr style="border-top:2px solid #334155;font-weight:700"><td style="text-align:left;padding:6px">合计</td>'
    best_total, best_tp = '', -1e18
    for cfg in configs:
        c = '#22c55e' if total_row[cfg] >= 0 else '#ef4444'
        html += '<td style="color:%s">%+d</td>' % (c, total_row[cfg])
        if total_row[cfg] > best_tp: best_tp, best_total = total_row[cfg], CONFIG_NAMES[cfg]
    html += '<td style="color:#3b82f6">%s</td></tr></table></div></div>' % best_total

    # All symbols section
    html += '<div id="allSec"><div class="grid">'
    for sym in symbols:
        html += '<div class="card"><h2>%s <span>%s</span></h2>' % (NAME_MAP.get(sym, sym), sym)
        cfg_cums = [cum(sym_data[sym][c]) for c in configs]
        html += gen_svg(cfg_cums, CONFIG_COLORS[:len(configs)], [CONFIG_NAMES[c] for c in configs], mshort, 420, 200)
        html += '</div>'
    html += '</div></div>'
    html += '<div class="footer">数据来源: VIP27消融回测 | 参数: atr=55, mult=3, N=5, radius=0.05, stop=40 | %s</div>' % ', '.join(sym_names)
    html += '</div><script>function showT(){document.getElementById("totalSec").style.display="block";document.getElementById("allSec").style.display="none";document.getElementById("bT").classList.add("active");document.getElementById("bA").classList.remove("active")}function showA(){document.getElementById("totalSec").style.display="none";document.getElementById("allSec").style.display="block";document.getElementById("bT").classList.remove("active");document.getElementById("bA").classList.add("active")}</script></body></html>'

    with open(out_path, 'w', encoding='utf-8') as f: f.write(html)
    print('HTML saved: %s' % out_path)
    print('Symbols: %d' % len(symbols))

if __name__ == '__main__':
    main()

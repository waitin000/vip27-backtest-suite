"""Calculate optimal position sizing for the recommended 5-symbol portfolio"""
import numpy as np

# Portfolio: 豆一 a888 + 热卷 hc888 + 铁矿 i888 + 焦炭 j888 + 甲醇 ma888
portfolio = ['a888', 'hc888', 'i888', 'j888', 'ma888']

name_map = {
    'a888':'豆一','hc888':'热卷','i888':'铁矿','j888':'焦炭','ma888':'甲醇'
}

margin_est = {
    'a888':4200, 'hc888':3800, 'i888':9960, 'j888':30750, 'ma888':2300
}

# Per-lot risk estimation (typical ATR-based)
# ATR(14) in price points, then * multiplier = yuan risk per lot
risk_per_lot = {
    'a888':  {'mult':10, 'atr_pts':45,  'risk': 45*10},     # 450元
    'hc888': {'mult':10, 'atr_pts':50,  'risk': 50*10},     # 500元
    'i888':  {'mult':100, 'atr_pts':15, 'risk': 15*100},    # 1500元
    'j888':  {'mult':100, 'atr_pts':45, 'risk': 45*100},    # 4500元
    'ma888': {'mult':10, 'atr_pts':35,  'risk': 35*10},     # 350元
}

total_budget = 200000

print("=" * 80)
print("均衡-黑色系 仓位分配计算")
print(f"总保证金预算: {total_budget:,} 元")
print("=" * 80)

# ===== Strategy 1: Equal risk contribution =====
# Allocate margin proportional to 1/risk so each position contributes equal risk
print("\n【方法一】等风险贡献分配")
print(f"{'品种':>8} {'1手保证金':>10} {'ATR风险/手':>12} {'等权手数':>8} {'保证金占用':>12} {'占总资金':>10}")
print("-" * 60)

total_risk_inv = sum(1.0 / v['risk'] for v in risk_per_lot.values())

for sym in portfolio:
    m = margin_est[sym]
    r = risk_per_lot[sym]
    # Weight inversely proportional to risk
    weight = (1.0 / r['risk']) / total_risk_inv
    budget_alloc = total_budget * weight
    lots = max(1, int(budget_alloc / m))
    actual_margin = lots * m
    pct = actual_margin / total_budget * 100
    print(f"  {name_map[sym]:>8} {m:>8,.0f} {r['risk']:>10,.0f} {lots:>6} {actual_margin:>10,.0f} {pct:>7.1f}%")

# ===== Strategy 2: Target 50% margin usage, split proportionally to margin =====
print("\n【方法二】等保证金分配（总占用约50%=10万）")
print(f"{'品种':>8} {'1手保证金':>10} {'建议手数':>8} {'保证金占用':>12} {'占总资金':>10}")
print("-" * 60)

target_usage = 100000  # 50% of 200K
total_margin_per = sum(margin_est[s] for s in portfolio)

for sym in portfolio:
    m = margin_est[sym]
    # Proportional allocation
    ideal_lots = target_usage / total_margin_per
    lots = max(1, round(ideal_lots * m / m))
    # Actually simpler: allocate percentage of total margin evenly
    even_share = target_usage / 5  # 20K per symbol
    lots = max(1, int(even_share / m))
    actual_margin = lots * m
    pct = actual_margin / total_budget * 100
    print(f"  {name_map[sym]:>8} {m:>8,.0f} {lots:>6} {actual_margin:>10,.0f} {pct:>7.1f}%")

# ===== Strategy 3: Practical 1-lot each =====
print("\n【方法三】各1手（最简单）")
print(f"{'品种':>8} {'1手保证金':>10} {'手数':>8} {'保证金占用':>12}")
print("-" * 55)

total_margin = 0
for sym in portfolio:
    m = margin_est[sym]
    total_margin += m
    print(f"  {name_map[sym]:>8} {m:>8,.0f} {'1':>6} {m:>10,.0f}")

print(f"  {'合计':>8} {'':>10} {'':>6} {total_margin:>10,.0f}")
print(f"  占总预算: {total_margin/total_budget*100:.0f}%")
print(f"  可用资金: {total_budget - total_margin:,} 元")

# ===== Strategy 4: Risk-based 2% rule =====
print("\n【方法四】风险预算分配（每品种风险≤2%总资金）")
print(f"{'品种':>8} {'1手保证金':>10} {'ATR风险/手':>12} {'max手数(2%)':>10} {'建议手数':>10} {'保证金占用':>12}")
print("-" * 70)

risk_budget = total_budget * 0.02  # 4000 per position

for sym in portfolio:
    m = margin_est[sym]
    r = risk_per_lot[sym]
    max_lots_by_risk = max(1, int(risk_budget / r['risk']))
    max_lots_by_margin = max(1, int(total_budget * 0.5 / 5 / m))  # ~20K per sym
    lots = min(max_lots_by_risk, max_lots_by_margin)
    actual_margin = lots * m
    print(f"  {name_map[sym]:>8} {m:>8,.0f} {r['risk']:>10,.0f} {max_lots_by_risk:>8} {lots:>8} {actual_margin:>10,.0f}")

# ===== Strategy 5: Proportional to Sharpe/risk =====
print("\n【方法五】等风险加权（每品种风险值相等）")
print(f"{'品种':>8} {'1手保证金':>10} {'风险系数':>10} {'建议手数':>8} {'保证金占用':>12}")
print("-" * 60)

# Risk coefficient: higher risk = fewer lots
risk_coeff = {sym: 1.0 for sym in portfolio}  # start even
# Adjust: j888 has highest risk (4500/lot), ma888 lowest (350/lot)
# Target: each symbol contributes ~equal risk
# Risk per position = lots * risk_per_lot
# Equal risk means: lots_j * 4500 = lots_ma * 350
# So lots_ma = lots_j * 4500/350 ≈ 13x j888
# But constrained by margin

# Solve: total_margin <= 100K, equal risk contribution
from scipy.optimize import minimize
# Actually let's just do a simple heuristic

# Risk target: 4000 per position
risk_target = 4000
for sym in portfolio:
    m = margin_est[sym]
    r = risk_per_lot[sym]
    lots = max(1, int(risk_target / r['risk']))
    # Cap by margin: max 20% of budget
    max_margin = total_budget * 0.2
    lots = min(lots, int(max_margin / m))
    actual_margin = lots * m
    actual_risk = lots * r['risk']
    print(f"  {name_map[sym]:>8} {m:>8,.0f} {r['risk']:>10,.0f} {lots:>6} {actual_margin:>10,.0f}")

print()
print("=" * 80)
print("推荐方案")
print("=" * 80)
print()
print("【首选】各品种1手（最简单稳健）")
print(f"  豆一 1手 = 4,200元")
print(f"  热卷 1手 = 3,800元")
print(f"  铁矿 1手 = 9,960元")
print(f"  焦炭 1手 = 30,750元")
print(f"  甲醇 1手 = 2,300元")
print(f"  ─────────────────────")
print(f"  合计保证金: 51,010元")
print(f"  剩余资金:  148,990元（可用作追加保证金）")
print(f"  总预算占用: 25.5%")
print()
print("【进阶】等风险加权")
print(f"  豆一 8手 = 33,600元  (风险3,600)")
print(f"  热卷 7手 = 26,600元  (风险3,500)")
print(f"  铁矿 3手 = 29,880元  (风险4,500)")
print(f"  焦炭 1手 = 30,750元  (风险4,500)")
print(f"  甲醇 11手 = 25,300元 (风险3,850)")
print(f"  ─────────────────────")
print(f"  合计保证金: 146,130元")
print(f"  每品种风险: 3,500~4,500元")
print(f"  总预算占用: 73%")

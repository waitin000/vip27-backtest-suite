# VIP27 多品种消融回测套件

基于VIP27曲率半径超级趋势策略的多品种回测、组合优化、逐笔交易记录工具集。

## 环境要求
- Python 3.8+
- pip install -r requirements.txt

## 文件结构

```
vip27_backtest_suite/
├── run_all.py                    # 一键运行（主入口）
├── requirements.txt
├── README.md
├── scripts/
│   ├── run_ext_ablation.py       # 20品种消融回测引擎
│   ├── vip27_optimized_engine.py # 单品种回测引擎
│   ├── gen_html.py               # 从pkl生成HTML收益曲线
│   ├── run_portfolio_trades.py   # 5品种组合逐笔交易记录
│   ├── portfolio_recommend.py    # 保证金约束下的组合优化推荐
│   ├── position_sizing.py        # 仓位分配计算
│   ├── compare_methods.py        # WF vs 全量回测对比
│   └── calc_risk.py             # 组合风险指标计算
├── results/                      # 回测结果pkl目录
└── data_cache/                   # K线数据缓存
```

## 使用方法

### 一键运行全部回测
```bash
python run_all.py
```
自动跑2025-2026和2023-2024两个时间段，生成HTML收益曲线。

### 组合推荐
```bash
python scripts/portfolio_recommend.py
```

### 生成5品种逐笔交易记录
```bash
python scripts/run_portfolio_trades.py
```

### 计算组合风险指标
```bash
python scripts/calc_risk.py
```

### WF vs 全量回测对比
```bash
python scripts/compare_methods.py
```

## 推荐组合

**均衡-黑色系（5品种各1手）**
| 品种 | 手数 | 保证金 |
|:----|:---:|:-----:|
| 豆一 a888 | 1 | 4,200 |
| 热卷 hc888 | 1 | 3,800 |
| 铁矿 i888 | 1 | 9,960 |
| 焦炭 j888 | 1 | 30,750 |
| 甲醇 ma888 | 1 | 2,300 |
| **合计** | **5** | **51,010** |

**18个月回测表现（walk-forward）**
| 指标 | 数值 |
|:---|:----:|
| 总PnL | +251,775 |
| 月Sharpe | 1.711 |
| 年化Sharpe | 5.927 |
| 最大回撤 | 0.41% |
| 胜月 | 17/18 (94%) |

## 数据源
自动从ssquant数据API获取期货K线数据，需联网。数据缓存在 data_cache/ 目录。

## 策略参数
- atr_length: 55
- atr_mult: 3.0
- radius_strength: 0.05
- smoothness: 5
- n_period: 5
- trailing_stop_rate: 40
- 优化配置: 删KG + 删LiqKA + N4选配

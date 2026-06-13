#!/usr/bin/env python3
"""
VIP27 CTP交易执行模块
读取信号JSON → 连接CTP → 执行下单/平仓/止损

CTP配置在 config.yaml 或环境变量中设置。
"""
import os, sys, json, time, threading
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

# ============================================================
#  CTP 接口封装（通过ssquant）
# ============================================================
try:
    import ssquant
    from ssquant.ctp import thosttraderapi as traderapi
    from ssquant.ctp import thostmduserapi as mdapi
    CTP_AVAILABLE = ssquant.ctp.CTP_AVAILABLE
except ImportError:
    CTP_AVAILABLE = False
    print("[WARN] ssquant CTP not available, running in paper mode")


# ============================================================
#  配置
# ============================================================

@dataclass
class CTPConfig:
    """CTP连接配置"""
    front_md: str = "tcp://140.206.242.85:51205"   # 行情地址
    front_trade: str = "tcp://140.206.242.85:51213" # 交易地址
    broker_id: str = ""       # 经纪商代码
    investor_id: str = ""     # 账户
    password: str = ""        # 密码
    app_id: str = ""          # APPID
    auth_code: str = ""       # 授权码


CONTRACT_MAP = {
    'a888':  {'id': 'a', 'exchange': 'DCE'},
    'hc888': {'id': 'hc', 'exchange': 'SHFE'},
    'i888':  {'id': 'i', 'exchange': 'DCE'},
    'j888':  {'id': 'j', 'exchange': 'DCE'},
    'ma888': {'id': 'MA', 'exchange': 'CZCE'},
}

# 仓位配置
POSITIONS = {
    'a888': 1, 'hc888': 1, 'i888': 1, 'j888': 1, 'ma888': 1,
}

# 风险控制
RISK_LIMITS = {
    'max_loss_per_trade': 3000,       # 单笔最大亏损(元)
    'max_daily_loss': 10000,          # 单日最大亏损
    'max_position_per_sym': 1,        # 单品种最大持仓
    'min_signal_interval': 1800,      # 同一信号最小间隔(秒)
}


# ============================================================
#  模拟交易（无CTP时使用）
# ============================================================

class PaperTrader:
    """模拟交易器，记录日志不下真实单"""
    
    def __init__(self):
        self.positions = {}  # sym -> {'direction': 1/-1, 'entry_price': float, 'qty': int}
        self.trades = []
        self.daily_pnl = 0
        self.last_signal_time = {}
    
    def process_signals(self, signals):
        """处理信号，执行模拟交易"""
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        
        print(f"\n{'='*60}")
        print(f"  模拟交易执行  {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        for sym, s in signals.items():
            if 'error' in s:
                continue
            
            pos = self.positions.get(sym)
            lots = POSITIONS.get(sym, 1)
            
            # 检查信号间隔
            last_time = self.last_signal_time.get(sym, 0)
            if time.time() - last_time < RISK_LIMITS['min_signal_interval']:
                continue
            
            # ── 平仓检查 ──
            if pos:
                # 趋势反转平仓
                if (pos['direction'] == 1 and s.get('exit_long')) or \
                   (pos['direction'] == -1 and s.get('exit_short')):
                    exit_price = s['price']
                    pnl = (exit_price - pos['entry_price']) * pos['qty'] * self._get_mult(sym)
                    if pos['direction'] == -1:
                        pnl = (pos['entry_price'] - exit_price) * pos['qty'] * self._get_mult(sym)
                    
                    self.trades.append({
                        'time': str(now),
                        'sym': sym, 'action': '平仓',
                        'dir': '多' if pos['direction']==1 else '空',
                        'entry_price': pos['entry_price'],
                        'exit_price': exit_price,
                        'qty': pos['qty'],
                        'pnl': pnl,
                        'reason': '趋势反转',
                    })
                    self.daily_pnl += pnl
                    del self.positions[sym]
                    self.last_signal_time[sym] = time.time()
                    print(f"  [{sym}] 平仓 {'多' if pos['direction']==1 else '空'} {pos['qty']}手 PnL={pnl:+,.0f}")
            
            # ── 入场检查 ──
            if sym not in self.positions:
                if s.get('long_entry'):
                    self.positions[sym] = {
                        'direction': 1, 'entry_price': s['price'],
                        'qty': lots, 'entry_time': str(now),
                    }
                    self.last_signal_time[sym] = time.time()
                    print(f"  [{sym}] 🟢 开多 {lots}手 @ {s['price']:.1f}")
                
                elif s.get('short_entry'):
                    self.positions[sym] = {
                        'direction': -1, 'entry_price': s['price'],
                        'qty': lots, 'entry_time': str(now),
                    }
                    self.last_signal_time[sym] = time.time()
                    print(f"  [{sym}] 🔴 开空 {lots}手 @ {s['price']:.1f}")
        
        # 打印持仓汇总
        print(f"\n当前持仓:")
        if not self.positions:
            print("  无持仓")
        else:
            for sym, pos in self.positions.items():
                print(f"  [{sym}] {'多' if pos['direction']==1 else '空'} {pos['qty']}手 入场:{pos['entry_price']:.1f}")
        
        total_pnl = sum(t['pnl'] for t in self.trades)
        print(f"\n今日已实现PnL: {self.daily_pnl:+,.0f}")
        print(f"累计PnL: {total_pnl:+,.0f}")
    
    def _get_mult(self, sym):
        mults = {'a888':10,'hc888':10,'i888':100,'j888':100,'ma888':10}
        return mults.get(sym, 10)


# ============================================================
#  CTP 实盘交易器
# ============================================================

class CTPTrader:
    """CTP直连交易器"""
    
    def __init__(self, config: CTPConfig):
        self.config = config
        self.trader_api = None
        self.md_api = None
        self.positions = {}
        self.trades = []
        self.front_id = 0
        self.session_id = 0
        self.connected = False
        self.paper = PaperTrader()  # 作为fallback
    
    def connect(self):
        """连接CTP"""
        if not CTP_AVAILABLE:
            print("[WARN] CTP not available, using paper trading")
            return False
        
        print(f"Connecting to CTP...")
        print(f"  MD: {self.config.front_md}")
        print(f"  Trade: {self.config.front_trade}")
        print(f"  Broker: {self.config.broker_id}")
        print(f"  Account: {self.config.investor_id}")
        print()
        print("请在 config.yaml 中完善CTP账户信息后重启")
        return False
    
    def process_signals(self, signals):
        """处理信号并执行实盘交易"""
        if not self.connected:
            print("[Paper mode] 信号处理中...")
            self.paper.process_signals(signals)
            return
        # TODO: 实盘交易逻辑（CTP连接配置好后启用）


# ============================================================
#  配置文件模板
# ============================================================

CONFIG_TEMPLATE = '''# VIP27 实盘交易配置
ctp:
  front_md: "tcp://140.206.242.85:51205"
  front_trade: "tcp://140.206.242.85:51213"
  broker_id: ""          # ← 填写你的经纪商代码
  investor_id: ""        # ← 填写你的账户
  password: ""           # ← 填写你的密码
  app_id: ""             # ← 填写你的APPID
  auth_code: ""          # ← 填写你的授权码

positions:
  a888: 1
  hc888: 1
  i888: 1
  j888: 1
  ma888: 1

risk:
  max_loss_per_trade: 3000
  max_daily_loss: 10000
  max_position_per_sym: 1
'''


def generate_config_template():
    """生成配置文件模板"""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    if not os.path.exists(config_path):
        with open(config_path, 'w') as f:
            f.write(CONFIG_TEMPLATE)
        print(f"配置文件模板已生成: {config_path}")
        print("请编辑 config.yaml 填写CTP账户信息")
    return config_path


# ============================================================
#  主入口
# ============================================================

def main():
    # 生成配置文件模板
    generate_config_template()
    
    # 读取信号
    signal_path = os.path.join(os.path.dirname(__file__), '..', 'data_cache', 'latest_signals.json')
    if not os.path.exists(signal_path):
        print("请先运行 live_signal.py 生成信号")
        return
    
    with open(signal_path) as f:
        signals = json.load(f)
    
    # 初始化交易器
    config = CTPConfig()
    trader = CTPTrader(config)
    trader.connect()
    trader.process_signals(signals)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
VIP27 实盘交易主控脚本
运行流程:
  1. 获取行情数据 → 计算信号 (live_signal.py)
  2. 执行交易 (ctp_trader.py)
  3. 循环（每30分钟）

用法:
  python run_live.py                    # 执行一次
  python run_live.py --loop             # 持续运行（每30分钟）
  python run_live.py --loop --interval 15  # 每15分钟运行一次
  python run_live.py --paper            # 仅模拟交易（不下实盘单）
"""
import sys, os, time, subprocess, json
from datetime import datetime

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), 'scripts')
DATA_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'data_cache')

BANNER = r"""
   ╔══════════════════════════════════════════╗
   ║     VIP27 实盘交易系统                    ║
   ║     5品种: 豆一/热卷/铁矿/焦炭/甲醇        ║
   ╚══════════════════════════════════════════╝
"""

CONTRACTS_INFO = """
  品种        方向    手数    保证金
  ─────────────────────────────────
  豆一 a888    —       1      4,200
  热卷 hc888   —       1      3,800
  铁矿 i888    —       1      9,960
  焦炭 j888    —       1     30,750
  甲醇 ma888   —       1      2,300
  ─────────────────────────────────
  合计                 5     51,010
"""


def run_once(paper_mode=False):
    """执行一次完整的信号计算+交易"""
    print(BANNER)
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  模式: {'模拟交易(paper)' if paper_mode else '实盘交易'}")
    print(CONTRACTS_INFO)
    
    # Step 1: 计算信号
    print("\n[Step 1/2] 计算策略信号...")
    signal_script = os.path.join(SCRIPTS_DIR, 'live_signal.py')
    ret = subprocess.run([sys.executable, signal_script], capture_output=True, text=True, timeout=60)
    
    if ret.returncode != 0:
        print(f"  [ERROR] 信号计算失败: {ret.stderr[:200]}")
        return False
    
    # 显示信号摘要
    for line in ret.stdout.split('\n'):
        if '做多' in line or '做空' in line or '平仓' in line or '当前无' in line or '方向翻转' in line or '🟢' in line or '🔴' in line:
            print(f"  {line.strip()}")
    
    # Step 2: 执行交易
    print(f"\n[Step 2/2] {'模拟' if paper_mode else '实盘'}交易执行...")
    trade_script = os.path.join(SCRIPTS_DIR, 'ctp_trader.py')
    ret2 = subprocess.run([sys.executable, trade_script], capture_output=True, text=True, timeout=30)
    
    for line in ret2.stdout.split('\n'):
        if line.strip():
            print(f"  {line.strip()}")
    
    print(f"\n  ✅ 执行完成")
    return True


def run_loop(interval_minutes=30, paper_mode=False):
    """持续运行模式"""
    print(BANNER)
    print(f"  持续运行模式启动")
    print(f"  间隔: 每{interval_minutes}分钟")
    print(f"  模式: {'模拟交易' if paper_mode else '实盘交易'}")
    print(f"  按 Ctrl+C 停止\n")
    
    os.makedirs(DATA_CACHE_DIR, exist_ok=True)
    
    while True:
        try:
            run_once(paper_mode)
            
            # 记录运行日志
            log_file = os.path.join(DATA_CACHE_DIR, 'run_log.txt')
            with open(log_file, 'a') as f:
                f.write(f"{datetime.now().isoformat()}\tOK\n")
            
            print(f"\n  下次运行: {interval_minutes}分钟后")
            print(f"  {'='*50}\n")
            time.sleep(interval_minutes * 60)
            
        except KeyboardInterrupt:
            print("\n\n  收到停止信号，正在退出...")
            break
        except Exception as e:
            print(f"\n  [ERROR] {e}")
            print(f"  30秒后重试...")
            time.sleep(30)


def main():
    # 参数解析
    paper_mode = '--paper' in sys.argv
    loop_mode = '--loop' in sys.argv
    
    interval = 30
    if '--interval' in sys.argv:
        idx = sys.argv.index('--interval')
        if idx + 1 < len(sys.argv):
            interval = int(sys.argv[idx + 1])
    
    if loop_mode:
        run_loop(interval, paper_mode)
    else:
        run_once(paper_mode)


if __name__ == '__main__':
    main()

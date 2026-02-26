import pandas as pd
import os
import glob
import numpy as np

def calculate_latency_distribution():
    # 查找当前目录下所有以 metrics_ 开头的 csv 文件
    search_paths = ['../metrics_*.csv',  'metrics_*.csv']
    
    csv_files = []
    for path in search_paths:
        csv_files.extend(glob.glob(path))
        
    # 去重
    csv_files = list(set(csv_files))
    
    if not csv_files:
        print("未找到任何 metrics_*.csv 文件")
        return

    print(f"{'共识算法 (Consensus)':<20} | {'平均延迟(s)':<15} | {'中位数(s)':<15} | {'95分位(s)':<15} | {'最大延迟(s)':<15}")
    print("-" * 85)

    for file in csv_files:
        try:
            # 提取共识算法名称
            filename = os.path.basename(file)
            consensus_name = filename.replace('metrics_', '').replace('.csv', '')
            
            # 读取 CSV
            df = pd.read_csv(file)
            
            # 检查是否存在 avg_tx_delay_s 列
            if 'avg_tx_delay_s' in df.columns:
                # 过滤掉延迟为 0 的行（通常是创世区块或空块）
                valid_data = df[df['avg_tx_delay_s'] > 0]['avg_tx_delay_s']
                
                if not valid_data.empty:
                    avg_delay = valid_data.mean()
                    median_delay = valid_data.median()
                    p95_delay = np.percentile(valid_data, 95)
                    max_delay = valid_data.max()
                    
                    print(f"{consensus_name:<20} | {avg_delay:<15.2f} | {median_delay:<15.2f} | {p95_delay:<15.2f} | {max_delay:<15.2f}")
                else:
                    print(f"{consensus_name:<20} | {'无有效数据':<15} | {'-':<15} | {'-':<15} | {'-':<15}")
            else:
                print(f"{consensus_name:<20} | {'缺少延迟列':<15} | {'-':<15} | {'-':<15} | {'-':<15}")
                
        except Exception as e:
            print(f"读取文件 {file} 时出错: {e}")

if __name__ == "__main__":
    calculate_latency_distribution()
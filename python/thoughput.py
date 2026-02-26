import pandas as pd
import os
import glob

def calculate_average_throughput():
    # 查找当前目录下所有以 metrics_slots_ 开头的 csv 文件
    # 假设你的 csv 文件在项目根目录或者 result 目录下
    search_paths = ['../metrics_slots_*.csv', 'metrics_slots_*.csv']
    
    csv_files = []
    for path in search_paths:
        csv_files.extend(glob.glob(path))
        
    # 去重
    csv_files = list(set(csv_files))
    
    if not csv_files:
        print("未找到任何 metrics_slots_*.csv 文件")
        return

    print(f"{'共识算法 (Consensus)':<20} | {'平均吞吐量 (Avg Throughput)':<25} | {'样本数 (Blocks)'}")
    print("-" * 65)

    for file in csv_files:
        try:
            # 提取共识算法名称
            filename = os.path.basename(file)
            consensus_name = filename.replace('metrics_slots_', '').replace('.csv', '')
            
            # 读取 CSV
            df = pd.read_csv(file)
            
            # 检查是否存在 throughput 列
            if 'throughput' in df.columns:
                # 过滤掉 throughput 为 0 的行（比如创世区块或刚启动时）
                valid_data = df[df['throughput'] > 0]
                
                if not valid_data.empty:
                    avg_throughput = valid_data['throughput'].mean()
                    count = len(valid_data)
                    print(f"{consensus_name:<20} | {avg_throughput:<25.2f} | {count}")
                else:
                    print(f"{consensus_name:<20} | {'无有效数据 (No valid data)':<25} | 0")
            else:
                print(f"{consensus_name:<20} | {'缺少 throughput 列':<25} | N/A")
                
        except Exception as e:
            print(f"读取文件 {file} 时出错: {e}")

if __name__ == "__main__":
    calculate_average_throughput()
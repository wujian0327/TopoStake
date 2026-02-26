import pandas as pd
import glob
import os

def calculate_average_path_length():
    # 查找当前目录和上一级目录下所有以 metrics_ 开头的 csv 文件
    search_paths = ['../metrics_*.csv', 'metrics_*.csv']
    
    csv_files = []
    for path in search_paths:
        csv_files.extend(glob.glob(path))

    # 去重
    csv_files = list(set(csv_files))
    
    if not csv_files:
        print("未找到任何 metrics_*.csv 文件")
        return

    print("交易平均路径长度统计：")
    print("-" * 50)
    
    for file in sorted(csv_files):
        try:
            df = pd.read_csv(file)
            
            # 确保包含所需的列
            if 'tx_count' not in df.columns or 'avg_path_length' not in df.columns:
                print(f"{os.path.basename(file)}: 缺少必要的列 (tx_count, avg_path_length)")
                continue
            
            # 过滤掉没有交易的区块
            df_with_tx = df[df['tx_count'] > 0]
            
            if len(df_with_tx) == 0:
                print(f"{os.path.basename(file)}: 无交易数据")
                continue
                
            # 计算加权平均路径长度 (真实的所有交易的平均路径长度)
            total_txs = df_with_tx['tx_count'].sum()
            weighted_avg_path_length = (df_with_tx['avg_path_length'] * df_with_tx['tx_count']).sum() / total_txs
            
            # 计算区块平均路径长度的简单平均值
            simple_avg_path_length = df_with_tx['avg_path_length'].mean()
            
            # 获取最大和最小路径长度
            max_path_length = df_with_tx['max_path_length'].max() if 'max_path_length' in df.columns else "N/A"
            min_path_length = df_with_tx['min_path_length'].min() if 'min_path_length' in df.columns else "N/A"
            
            print(f"文件: {os.path.basename(file)}")
            print(f"  总交易数: {total_txs}")
            print(f"  加权平均路径长度 (真实交易平均): {weighted_avg_path_length:.4f}")
            print(f"  区块平均路径长度 (简单平均): {simple_avg_path_length:.4f}")
            print(f"  最大路径长度: {max_path_length}")
            print(f"  最小路径长度: {min_path_length}")
            print("-" * 50)
            
        except Exception as e:
            print(f"处理文件 {file} 时出错: {e}")

if __name__ == "__main__":
    calculate_average_path_length()

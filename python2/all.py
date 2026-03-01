import os
import subprocess
import sys

def main():
    # 获取当前目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 项目根目录 (all.py 的上一级)
    project_root = os.path.dirname(current_dir)
    
    # 忽略不直接运行的脚本
    ignore_files = {'all.py', 'plot_style.py'}
    
    # 获取所有需要的 python 文件
    py_files = [f for f in os.listdir(current_dir) if f.endswith('.py') and f not in ignore_files]
    py_files.sort()
    
    print(f"[*] Found {len(py_files)} python scripts to run.")
    
    success_count = 0
    fail_count = 0
    
    # 确保 figures 目录存在
    os.makedirs(os.path.join(project_root, 'figures'), exist_ok=True)
    
    for py_file in py_files:
        print(f"\n{'='*50}")
        print(f"[*] Running {py_file}...")
        print(f"{'='*50}")
        
        file_path = os.path.join(current_dir, py_file)
        
        try:
            # 运行脚本，cwd设置成项目根目录
            subprocess.run([sys.executable, file_path], cwd=project_root, check=True)
            print(f"[+] Successfully ran {py_file}")
            success_count += 1
        except subprocess.CalledProcessError as e:
            print(f"[-] Error running {py_file}: Return code {e.returncode}")
            fail_count += 1
            
    print(f"\n{'='*50}")
    print(f"[*] Done. {success_count} succeeded, {fail_count} failed.")

if __name__ == "__main__":
    main()

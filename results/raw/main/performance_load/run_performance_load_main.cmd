@echo off
cd /d "E:\code\pog-rs"
set TOPOSTAKE_LOG_LEVEL=off
"C:\Users\ASUS\Miniconda3\python.exe" -u experiments\run_experiments.py --config experiments\configs\main.yaml --only performance_load --force > "E:\code\pog-rs\results\raw\main\performance_load\_runner_performance_load.out.log" 2> "E:\code\pog-rs\results\raw\main\performance_load\_runner_performance_load.err.log"

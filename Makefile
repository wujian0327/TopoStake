.PHONY: test bench experiments-smoke experiments-main summarize figures

test:
	cargo fmt --check
	cargo check
	cargo test

bench:
	CRITERION_QUICK=1 cargo bench --bench bls_path -- --quiet

experiments-smoke:
	python3 experiments/run_experiments.py --config experiments/configs/smoke.yaml
	python3 experiments/summarize.py --config experiments/configs/smoke.yaml
	$(MAKE) figures

experiments-main:
	python3 experiments/run_experiments.py --config experiments/configs/main.yaml
	python3 experiments/summarize.py --config experiments/configs/main.yaml

summarize:
	python3 experiments/summarize.py

figures:
	python3 analysis/plot_performance.py
	python3 analysis/plot_crypto_overhead.py
	python3 analysis/plot_fairness.py
	python3 analysis/plot_weight_bound.py
	python3 analysis/plot_padding_flooding.py
	python3 analysis/plot_churn.py

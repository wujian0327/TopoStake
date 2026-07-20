```
# 1. Security
python scripts/task.py frozen-security-figures

# 2. Fee bonus
python scripts/task.py frozen-fee-bonus-figures \
  --config experiments/configs/frozen_v1_fee_bonus_main.yaml

# 3. Organic capture
python scripts/task.py frozen-organic-capture-figures \
  --config experiments/configs/frozen_v1_organic_capture_main.yaml

# 4. Sustained outage
python scripts/task.py frozen-sustained-outage-figures \
  --config experiments/configs/frozen_v1_sustained_outage_main.yaml

# 5. Devnet
python scripts/task.py frozen-devnet-figures
```

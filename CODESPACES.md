# Run the experiment in GitHub Codespaces (CPU)

This is the recommended browser-based fallback when Kaggle is unavailable. No local installation and no GPU are required.

## Create the Codespace

1. Open the repository's Codespaces creation page:
   https://github.com/codespaces/new?repo=itsilsil/structured-reasoning-llm
2. Sign in to GitHub if asked.
3. Choose the `main` branch.
4. Choose the **2-core** machine (8 GB RAM). Do not choose a larger machine because it may use paid quota.
5. Click **Create codespace** and wait for the browser-based VS Code editor to open.

Personal GitHub Free accounts currently include 120 core-hours and 15 GB-month storage per month. A 2-core Codespace uses 2 core-hours per hour, so this is up to 60 hours of runtime, subject to the account's remaining quota and storage use. Check GitHub's current billing page before proceeding if you have already used Codespaces this month.

## Run the 2-question smoke test

When the editor opens:

1. Open **Terminal → New Terminal**.
2. Paste these commands, one at a time:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 python src/experiment.py --sample-size 2 --seed 42 --num-candidates 2 --max-new-tokens 96
```

The first run downloads the model and GSM8K dataset, so it needs internet access and may take a while.

## Inspect and export results

After the run finishes:

```bash
cat results/summary.csv
```

The output files are:
- `results/summary.csv`
- `results/experiment_results.jsonl`
- `results/run_config.json`

To save the results back to GitHub, use the Source Control panel in the browser editor, stage the three result files, commit, and push. Do not commit model weights or cache files.

## Important

- Start with 2 questions only. Do not run the 10-question pilot until the smoke test completes.
- Stop the Codespace when finished: open https://github.com/codespaces and use the menu next to the active Codespace to stop it. Stopping prevents further compute usage.
- Never enable paid usage or select a larger machine unless you explicitly decide to.

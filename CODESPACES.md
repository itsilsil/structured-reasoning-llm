# View and analyze project results in GitHub Codespaces

The 10-question pilot experiment has already been completed. Its saved outputs are in the repository's `results/` directory. **You do not need to run the model again to use either the dashboard or the analysis notebook.**

## Option 1: Interactive dashboard (recommended)

In the Codespaces terminal, run:

```bash
pip install -r requirements-dashboard.txt
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

When Codespaces detects port **8501**, open the **Ports** tab and choose **Open in Browser**.

The dashboard provides:
- Method comparison charts for accuracy, generated tokens, generation calls, and judge-format failures.
- Per-question inspection: problem statement, gold answer, model answer, correctness, token count, and raw model output.
- ToT-inspired candidate paths and judge output.
- Comparison of saved runs under `results/` and `runs/`.
- Downloads for CSV, JSONL, JSON configuration, Markdown report, and a ZIP bundle.

The dashboard reads saved files only. It does not load Qwen or run inference.

## Option 2: Analysis notebook

1. Open `notebooks/codespaces_results_analysis.ipynb` in the VS Code editor.
2. Select the Python kernel for the current Codespace.
3. If the required packages are not installed, run:

   ```bash
   pip install -r requirements-dashboard.txt
   ```

4. Run the notebook cells from top to bottom.

The notebook displays the experiment configuration, comparison charts, per-question results, raw model outputs, and ToT-inspired candidate/judge details. It also saves `results/question_details.csv`.

## Saved result files

- `results/summary.csv`: aggregate metrics for the three methods.
- `results/experiment_results.jsonl`: raw outputs and per-question metadata.
- `results/run_config.json`: model and experiment configuration.
- `results/question_report.md`: detailed written report.

## Optional: run a new experiment

Only run this section if you intentionally want to collect additional results. It is not needed to view the completed 10-question pilot.

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 python src/experiment.py --sample-size 2 --seed 42 --num-candidates 2 --max-new-tokens 96 --output-dir runs/new_smoke_test
```

Use a new directory under `runs/` so that the existing `results/` files are not overwritten. To run a larger sample, change `--sample-size` deliberately; remember that CPU inference can take a long time.

## Stop the Codespace

When finished, stop the Codespace from the GitHub Codespaces page or the Codespaces menu. This prevents it from continuing to run while you are not using it.

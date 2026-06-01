# Quick Start Guide

Get started analyzing Polish investment funds in 5 minutes!

> ⚠️ **Data-source status — read this first.** Stooq's free feed no longer works
> out of the box: the fund-listing page is now a JavaScript app (nothing to
> scrape) and the CSV quote endpoint requires a captcha-issued API key. **The
> recommended path is the `analizy.pl` provider** (shown below) — it needs no
> key. Run `python doctor.py` at any time to see exactly what's working.

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

This installs all required packages: pandas, requests, beautifulsoup4, numpy, scipy, matplotlib, seaborn, openpyxl, and tqdm.

## Step 2: Check Your Setup

```bash
python doctor.py            # same as: python analyze_polish_funds.py --self-test
```

This verifies your Python version, dependencies, network, and each data source,
printing a clear `[PASS]`/`[WARN]`/`[FAIL]` for each. On a healthy machine the
`analizy.pl` source is green; Stooq will warn about its API key — that's expected.

## Step 3: Run Your First Analysis

### Recommended: analizy.pl funds (no API key needed)
```bash
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt
```

This will:
- Download NAV history for each fund symbol in the file
- Analyze returns and risk metrics
- Generate `funds_analysis.csv` and `funds_analysis.html`
- Show results in the terminal

To screen your own funds, add their symbols (one per line) to a symbols file.
Find a fund's symbol in its analizy.pl URL, e.g. `…/ING35` → `ING35`.

### Alternative: Stooq (requires an API key)
Stooq now gates its CSV endpoint. Get a key (one-time captcha) at
<https://stooq.pl/q/d/?s=wig&get_apikey>, then:
```bash
export STOOQ_APIKEY=your_key_here       # or pass --stooq-apikey your_key
python analyze_polish_funds.py --provider stooq \
    --symbols-file your_stooq_symbols.txt
```
Even with a key, Stooq's bulk fund *listing* is unavailable (it's a JS app now),
so you must supply symbols with `--symbols-file`.

### View Results

Open `funds_analysis.html` in your web browser to see a formatted report with:
- Summary statistics
- Color-coded recommendations
- All metrics in an easy-to-read table

## Step 4: Try Different Options

The examples below use the analizy provider; swap in your own `--symbols-file`.

### Generate Excel Report
```bash
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt --format excel html
```
Opens easily in Excel/LibreOffice Calc

### Create Visualizations
```bash
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt --plots
```
Creates charts in `plots/` directory

### Limit How Many Funds to Analyze
```bash
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt --max-funds 10
```
Analyzes the first 10 symbols from the file (`--max-funds 0` = all of them).

## Step 5: Customize Your Analysis

### Use Different Scoring Strategies

**Conservative** (focus on safety):
```bash
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt \
    --score-config scoring_configs/conservative.json
```

**Aggressive** (focus on growth):
```bash
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt \
    --score-config scoring_configs/aggressive.json
```

**Balanced** (default weights):
```bash
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt \
    --score-config scoring_configs/balanced.json
```

## Common Workflows

### Interactive Dashboard
```bash
streamlit run dashboard.py
```
Opens a point-and-click UI in your browser. It starts in **Demo mode** (synthetic
data) so you can explore without any network access — turn Demo mode off in the
sidebar to use live data.

### Compare Strategies
```bash
# Conservative
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt \
    --score-config scoring_configs/conservative.json \
    --output conservative_results

# Aggressive
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt \
    --score-config scoring_configs/aggressive.json \
    --output aggressive_results

# Compare the HTML reports side-by-side!
```

### Export for Spreadsheet Analysis
```bash
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt --format excel json
```

## Understanding Your Results

### In the HTML Report

**Green rows (Buy)**: Funds with strong performance across multiple metrics
- High returns
- Good risk-adjusted performance (Sharpe/Sortino ratios)
- Limited drawdowns

**Yellow rows (Hold)**: Funds with average performance
- Moderate returns
- Acceptable risk levels
- May be suitable depending on your goals

**Red rows (Sell)**: Funds with weak performance
- Low or negative returns
- Poor risk-adjusted performance
- Large drawdowns

### Key Metrics to Watch

1. **Score**: Overall rating (0-100). Higher is better.
2. **6M Return**: Recent performance. >10% is strong.
3. **Sharpe Ratio**: Risk-adjusted return. >1.0 is good, >2.0 is excellent.
4. **Max Drawdown**: Worst decline. Closer to 0% is better (less risky).
5. **Percentile Rank**: How this fund compares to others. >90% = top 10%.

## Troubleshooting

### "No module named 'pandas'" (or matplotlib, seaborn, …)
Run: `pip install -r requirements.txt`. If you use a virtualenv, make sure it's
activated so the script runs under the interpreter that has the packages.

### `RuntimeError: ... fund listing ... JavaScript app` (Stooq)
Stooq's bulk listing no longer works. Use the analizy provider with a symbols
file, or supply Stooq symbols with `--symbols-file`. Run `python doctor.py` to
confirm which sources are up.

### `Error: Stooq requires an API key`
Stooq gated its CSV endpoint. Get a key at
<https://stooq.pl/q/d/?s=wig&get_apikey> and set `STOOQ_APIKEY` (or pass
`--stooq-apikey`), or simply use `--provider analizy`.

### "Connection timeout" or network errors
- Check your internet connection
- Some funds may be temporarily unavailable (warnings shown)
- Try again later

### Analysis is slow
- Analyze fewer funds: `--max-funds 50`
- Increase workers: `--workers 20`
- Enable cache (default - it will be faster on the second run)

### Can't see plots
- Make sure matplotlib is installed: `pip install matplotlib seaborn`
- Use the `--plots` flag
- Check the `plots/` directory for PNG files

## Next Steps

1. **Read the full README.md** for detailed documentation
2. **Experiment with different settings** to find what works for you
3. **Review the scoring configs** in `scoring_configs/README.md`
4. **Customize scoring weights** for your investment strategy
5. **Compare results over time** to track fund performance

## Pro Tips

💡 **Run twice**: First run downloads data (slower), second run uses cache (much faster)

💡 **Start small**: Test with a few symbols first, then add more to your symbols file

💡 **Use Excel**: The Excel export makes it easy to sort, filter, and create custom charts

💡 **Check HTML daily**: The HTML report is perfect for quick reviews

💡 **Compare strategies**: Run with different configs to see how recommendations change

💡 **Clear cache weekly**: `--clear-cache` to ensure fresh data for important decisions

## Example Session

```bash
# Install dependencies (one time)
pip install -r requirements.txt

# Check everything works
python doctor.py

# First analysis (analizy.pl funds)
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt --plots

# View results
open funds_analysis.html      # Mac
xdg-open funds_analysis.html  # Linux
start funds_analysis.html     # Windows

# Try a different strategy
python analyze_polish_funds.py --provider analizy \
    --symbols-file sample_symbols_analizy.txt \
    --score-config scoring_configs/conservative.json \
    --output conservative_analysis
```

## Getting Help

- **Full documentation**: See README.md
- **Environment check**: `python doctor.py`
- **Command help**: `python analyze_polish_funds.py --help`
- **Scoring strategies**: See scoring_configs/README.md
- **Code documentation**: Read the docstrings in analyze_polish_funds.py

---

**Ready to start? Run this now:**

```bash
python doctor.py && python analyze_polish_funds.py \
    --provider analizy --symbols-file sample_symbols_analizy.txt
```

Then open `funds_analysis.html` in your browser! 🚀

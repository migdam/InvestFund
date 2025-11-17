# Quick Start Guide

Get started analyzing Polish investment funds in 5 minutes!

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

This installs all required packages: pandas, requests, beautifulsoup4, numpy, scipy, matplotlib, seaborn, openpyxl, and tqdm.

## Step 2: Run Your First Analysis

### Basic Analysis (50 funds)
```bash
python analyze_polish_funds.py
```

This will:
- Download data for the first 50 funds
- Analyze returns and risk metrics
- Generate `funds_analysis.csv` and `funds_analysis.html`
- Show results in the terminal

**Time**: ~2-3 minutes

### View Results

Open `funds_analysis.html` in your web browser to see a beautiful formatted report with:
- Summary statistics
- Color-coded recommendations
- All metrics in an easy-to-read table

## Step 3: Try Different Options

### Generate Excel Report
```bash
python analyze_polish_funds.py --format excel html
```
Opens easily in Excel/LibreOffice Calc

### Create Visualizations
```bash
python analyze_polish_funds.py --plots
```
Creates charts in `plots/` directory

### Analyze More Funds
```bash
python analyze_polish_funds.py --max-funds 100
```
Analyzes first 100 funds (~5 minutes)

### Analyze ALL Funds
```bash
python analyze_polish_funds.py --max-funds 0 --workers 20
```
Analyzes all available funds (may take 10-30 minutes depending on total number)

## Step 4: Customize Your Analysis

### Use Different Scoring Strategies

**Conservative** (focus on safety):
```bash
python analyze_polish_funds.py --score-config scoring_configs/conservative.json
```

**Aggressive** (focus on growth):
```bash
python analyze_polish_funds.py --score-config scoring_configs/aggressive.json
```

**Balanced** (default - already used):
```bash
python analyze_polish_funds.py --score-config scoring_configs/balanced.json
```

## Common Workflows

### Daily Quick Check
```bash
# Fast analysis using yesterday's cache
python analyze_polish_funds.py --max-funds 50
```

### Weekly Deep Dive
```bash
# Comprehensive analysis with fresh data
python analyze_polish_funds.py --no-cache --max-funds 200 --plots --format excel html
```

### Compare Strategies
```bash
# Conservative
python analyze_polish_funds.py --score-config scoring_configs/conservative.json \
    --output conservative_results

# Aggressive
python analyze_polish_funds.py --score-config scoring_configs/aggressive.json \
    --output aggressive_results

# Compare the HTML reports side-by-side!
```

### Export for Spreadsheet Analysis
```bash
python analyze_polish_funds.py --format excel json --max-funds 100
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

### "No module named 'pandas'"
Run: `pip install -r requirements.txt`

### "Connection timeout" or network errors
- Check your internet connection
- Some funds may be temporarily unavailable (warnings shown)
- Try again later

### Analysis is slow
- Use fewer funds: `--max-funds 50`
- Increase workers: `--workers 20`
- Enable cache (default - it will be faster on second run)

### Can't see plots
- Make sure matplotlib is installed: `pip install matplotlib seaborn`
- Use `--plots` flag
- Check `plots/` directory for PNG files

## Next Steps

1. **Read the full README.md** for detailed documentation
2. **Experiment with different settings** to find what works for you
3. **Review the scoring configs** in `scoring_configs/README.md`
4. **Customize scoring weights** for your investment strategy
5. **Compare results over time** to track fund performance

## Pro Tips

💡 **Run twice**: First run downloads data (slower), second run uses cache (much faster)

💡 **Start small**: Test with 50 funds first, then scale up

💡 **Use Excel**: The Excel export makes it easy to sort, filter, and create custom charts

💡 **Check HTML daily**: The HTML report is perfect for quick reviews

💡 **Compare strategies**: Run with different configs to see how recommendations change

💡 **Clear cache weekly**: `--clear-cache` to ensure fresh data for important decisions

## Example Session

```bash
# Install dependencies (one time)
pip install -r requirements.txt

# First analysis
python analyze_polish_funds.py --max-funds 100 --plots

# View results
open funds_analysis.html  # Mac
xdg-open funds_analysis.html  # Linux
start funds_analysis.html  # Windows

# Later the same day (uses cache - fast!)
python analyze_polish_funds.py --max-funds 100

# Try different strategy
python analyze_polish_funds.py --max-funds 100 \
    --score-config scoring_configs/conservative.json \
    --output conservative_analysis

# Compare the two HTML reports to see the difference!
```

## Getting Help

- **Full documentation**: See README.md
- **Command help**: `python analyze_polish_funds.py --help`
- **Scoring strategies**: See scoring_configs/README.md
- **Code documentation**: Read the docstrings in analyze_polish_funds.py

---

**Ready to start? Run this now:**

```bash
python analyze_polish_funds.py
```

Then open `funds_analysis.html` in your browser! 🚀

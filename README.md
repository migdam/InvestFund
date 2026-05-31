# Polish Investment Funds Analyzer

A comprehensive Python tool for analyzing Polish investment funds listed on [Stooq.pl](https://stooq.pl). This enhanced version provides advanced financial metrics, risk analysis, and intelligent recommendations.

## Features

### Core Analysis
- **Multiple Return Periods**: 1-month, 3-month, 6-month, 1-year, and year-to-date returns
- **Risk Metrics**:
  - Annualized volatility
  - Maximum drawdown
  - Value at Risk (VaR) and Conditional VaR
- **Risk-Adjusted Returns**:
  - Sharpe ratio
  - Sortino ratio
  - Calmar ratio
- **Statistical Analysis**:
  - Skewness and kurtosis
  - Distribution analysis

### Performance Features
- **Parallel Processing**: Concurrent fund analysis for faster execution
- **Smart Caching**: Reduces network requests and speeds up repeated analyses
- **Progress Tracking**: Real-time progress bars for long-running operations

### Output Formats
- **CSV**: Simple comma-separated values
- **Excel**: Formatted spreadsheets with auto-sized columns
- **JSON**: Machine-readable structured data
- **HTML**: Beautiful interactive reports with styling and summaries

### Visualization
- Return distribution histograms
- Risk-return scatter plots
- Recommendation breakdowns
- Top performers charts
- Advanced metrics comparisons

### Intelligent Recommendations
Multi-factor scoring system considering:
- Historical returns (1m, 6m, 1y)
- Risk-adjusted performance (Sharpe, Sortino ratios)
- Drawdown protection
- Customizable scoring weights

## Installation

### Prerequisites
- Python 3.8 or higher
- pip package manager

### Setup

1. Clone or download this repository:
```bash
git clone <repository-url>
cd InvestFund
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Interactive Dashboard

For a point-and-click experience, run the Streamlit dashboard instead of the CLI:

```bash
pip install streamlit          # if not already installed
streamlit run dashboard.py
```

It opens in your browser with two views:

- **Fund Screener** — run the analysis, filter by recommendation and minimum
  score, sort the table, view risk/return and score charts, and download
  CSV/JSON. Supports an optional benchmark ticker.
- **Portfolio Tracker** — upload a holdings file (JSON/CSV) to see value, P&L,
  allocation, and an interactive fee-drag projection (adjust horizon and assumed
  return with sliders).

A **Demo mode** toggle (on by default) generates synthetic data, so you can try
the whole interface without any network access. Turn it off to use live data.

## Usage

### Basic Usage

Analyze the first 50 funds (default):
```bash
python analyze_polish_funds.py
```

### Common Examples

**Analyze all funds:**
```bash
python analyze_polish_funds.py --max-funds 0
```

**Generate Excel and HTML reports:**
```bash
python analyze_polish_funds.py --format excel html --output my_analysis
```

**Create visualizations:**
```bash
python analyze_polish_funds.py --plots
```

**Disable caching for fresh data:**
```bash
python analyze_polish_funds.py --no-cache
```

**Use more parallel workers (faster):**
```bash
python analyze_polish_funds.py --workers 20
```

**Custom output filename:**
```bash
python analyze_polish_funds.py --output results/fund_report_2024
```

### Advanced Usage

**Custom scoring weights:**

Create a JSON file `custom_weights.json`:
```json
{
  "return_6m": 0.30,
  "return_1y": 0.25,
  "sharpe_ratio": 0.20,
  "sortino_ratio": 0.15,
  "max_drawdown": 0.10
}
```

Then run:
```bash
python analyze_polish_funds.py --score-config custom_weights.json
```

**Clear cache:**
```bash
python analyze_polish_funds.py --clear-cache
```

## Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--max-funds N` | Maximum number of funds to analyze (0 = all) | 50 |
| `--output PATH` | Base path for output files | `funds_analysis` |
| `--format FORMATS` | Output formats (csv, excel, json, html) | `csv html` |
| `--no-cache` | Disable caching (always download fresh data) | False |
| `--workers N` | Number of parallel workers | 10 |
| `--plots` | Generate visualization plots | False |
| `--score-config PATH` | Path to custom scoring weights JSON | None |
| `--clear-cache` | Clear cache directory and exit | False |
| `--benchmark TICKER` | Compute benchmark-relative metrics vs a market index | None |
| `--correlation` | Build a correlation matrix and flag redundant holdings | False |
| `--portfolio PATH` | Track a holdings file (JSON/CSV): value, P&L, allocation, fees | None |
| `--project-years N` | Horizon for portfolio fee-drag projection | 10 |
| `--assumed-return R` | Assumed gross annual return for fee projection | 0.06 |

## Benchmark Comparison

Pass a market index with `--benchmark` to answer the key question: *is a fund
actually beating the market, or just riding it?*

```bash
# Compare every fund against the WIG index
python analyze_polish_funds.py --benchmark wig --format html
```

This adds the following columns to every report:

| Metric | Meaning |
|--------|---------|
| `beta` | Sensitivity to benchmark moves (1.0 = moves with the market) |
| `alpha` | Annualized excess return *after* adjusting for beta (CAPM). Positive = genuine outperformance |
| `tracking_error` | Annualized volatility of the fund's active return vs the benchmark |
| `information_ratio` | Active return per unit of tracking error (consistency of outperformance) |
| `up_capture` | Share of the benchmark's up-moves captured (>1 = amplifies gains) |
| `down_capture` | Share of the benchmark's down-moves captured (<1 = cushions losses) |

Returns and the benchmark are aligned on common trading days, so funds that
trade on different calendars are still compared fairly. A fund needs at least
60 overlapping days for these metrics to be computed.

## Correlation & Diversification

Use `--correlation` to see which funds move together. Holding several highly
correlated funds adds little diversification — this surfaces the redundant pairs.

```bash
python analyze_polish_funds.py --max-funds 30 --correlation
```

This writes a full correlation matrix to `<output>_correlation.csv` and prints
any pairs with correlation ≥ 0.80 (limited diversification) to the console.

## Portfolio Tracking

Track what you actually own. Provide a holdings file with `--portfolio` and the
tool values each position, computes profit/loss, allocation, and a value-weighted
return — then exports the result and prints a summary.

```bash
# Value your holdings (see sample_portfolio.json for the format)
python analyze_polish_funds.py --portfolio sample_portfolio.json --format csv json
```

**Holdings file** — JSON (a list, or `{"holdings": [...]}`) or CSV with columns
`symbol,shares,cost_basis[,ter,name]`:

```json
{
  "holdings": [
    {"symbol": "1006.N", "shares": 100, "cost_basis": 45.50, "ter": 0.018, "name": "Equity Fund"},
    {"symbol": "1007.N", "shares": 250, "cost_basis": 12.30, "ter": 0.012, "name": "Bond Fund"}
  ]
}
```

- `cost_basis` — price paid per share
- `ter` *(optional)* — annual expense ratio (e.g. `0.018` = 1.8%), used for fee analysis

Each position reports current price, current value, unrealized P&L (absolute and
%), portfolio weight, 1-year return, and estimated annual fee cost. Holdings whose
data can't be fetched are still listed but excluded from totals.

## Fee-Drag Projection

Expense ratios are small per year but compound brutally over decades. When your
holdings include a `ter`, portfolio mode projects how much those fees cost you:

```bash
python analyze_polish_funds.py --portfolio sample_portfolio.json \
    --project-years 20 --assumed-return 0.06
```

It compounds your current portfolio value over the horizon at the assumed gross
return, both with and without the (value-weighted average) TER, and reports the
terminal value lost to fees. Defaults: `--project-years 10`, `--assumed-return 0.06`.

## Output Files

### CSV Format
Simple comma-separated file with all metrics:
- `funds_analysis.csv` - Default output

### Excel Format
Formatted spreadsheet with:
- Auto-sized columns
- All metrics in a single sheet
- Easy to filter and sort

### JSON Format
Structured data suitable for:
- Further programmatic processing
- Integration with other tools
- Custom analysis scripts

### HTML Format
Interactive report featuring:
- Summary statistics
- Color-coded recommendations (Buy/Hold/Sell)
- Sortable table
- Professional styling
- Responsive design

### Visualizations (with `--plots`)
Generated in `plots/` directory:
- `fund_analysis_overview.png`:
  - Return distribution histogram
  - Recommendation pie chart
  - Risk-return scatter plot
  - Top 10 funds by score
- `fund_analysis_metrics.png`:
  - Sharpe vs Sortino comparison
  - Maximum drawdown distribution
  - Volatility vs drawdown scatter
  - Score distribution

## Understanding the Metrics

### Return Metrics
- **1M/3M/6M/1Y Return**: Simple percentage return over the period
- **YTD Return**: Year-to-date return from January 1st

### Risk Metrics
- **Volatility**: Annualized standard deviation of returns (higher = more risky)
- **Maximum Drawdown**: Largest peak-to-trough decline (negative percentage)
- **VaR 95%**: Value at Risk - maximum expected loss 95% of the time
- **CVaR 95%**: Conditional VaR - average loss in worst 5% of cases

### Risk-Adjusted Returns
- **Sharpe Ratio**: Excess return per unit of total risk
  - \>2.0: Excellent
  - 1.0-2.0: Very good
  - 0.5-1.0: Good
  - <0.5: Poor
- **Sortino Ratio**: Like Sharpe but only considers downside volatility
- **Calmar Ratio**: Return divided by maximum drawdown

### Statistical Measures
- **Skewness**: Asymmetry of return distribution
  - Positive: More extreme positive returns
  - Negative: More extreme negative returns
- **Kurtosis**: "Tailedness" of distribution
  - High: More extreme events (fat tails)
  - Low: Fewer extreme events

### Recommendation System
Funds are scored 0-100 based on multiple factors:
- **Buy** (Score ≥70): Strong performance across metrics
- **Hold** (Score 40-69): Average performance
- **Sell** (Score <40): Weak performance

**Score Components** (default weights):
- 6-month return: 25%
- 1-year return: 20%
- Sharpe ratio: 25%
- Sortino ratio: 15%
- Maximum drawdown: 15%

## Caching Behavior

The analyzer caches:
1. **Fund list**: Cached for 1 day
2. **Historical quotes**: Cached for 1 day per fund

Cache location: `.fund_cache/` directory

Benefits:
- Faster repeated analyses
- Reduced network load
- Ability to work offline (if cache is fresh)

To force fresh data: `--no-cache`
To clear cache: `--clear-cache`

## Performance Tips

1. **Use parallel workers**: `--workers 20` for faster analysis
2. **Enable caching**: Don't use `--no-cache` for repeated runs
3. **Limit funds initially**: Start with `--max-funds 100` to test
4. **Skip plots**: Omit `--plots` if you don't need visualizations

## Examples

### Quick Analysis of Top 100 Funds
```bash
python analyze_polish_funds.py --max-funds 100 --format csv html
```

### Comprehensive Analysis with Visualizations
```bash
python analyze_polish_funds.py --max-funds 0 --format excel html json --plots --workers 15
```

### Daily Update (Using Cache)
```bash
# First run - downloads all data
python analyze_polish_funds.py --max-funds 200

# Later that day - uses cache (much faster)
python analyze_polish_funds.py --max-funds 200
```

### Fresh Analysis (No Cache)
```bash
python analyze_polish_funds.py --no-cache --max-funds 50
```

## Troubleshooting

### Slow Performance
- Increase workers: `--workers 20`
- Enable caching (default)
- Reduce fund count: `--max-funds 50`

### Network Errors
- Check internet connection
- Some funds may be temporarily unavailable (warnings will be shown)
- Try again later or use `--no-cache` to refresh

### Missing Plots
- Install matplotlib and seaborn: `pip install matplotlib seaborn`
- Check that `--plots` flag is used

### Excel Export Fails
- Install openpyxl: `pip install openpyxl`

## Limitations and Disclaimers

⚠️ **IMPORTANT DISCLAIMERS**:

1. **Not Financial Advice**: This tool is for informational and educational purposes only. It does NOT constitute professional investment advice.

2. **Consult Professionals**: Always consult a qualified financial advisor before making investment decisions.

3. **Past Performance**: Historical returns do not guarantee future results.

4. **Data Accuracy**: Data is sourced from Stooq.pl. Verify important data independently.

5. **Simplified Model**: The recommendation system uses simplified rules and may not account for:
   - Your personal financial situation
   - Investment goals and time horizon
   - Risk tolerance
   - Tax implications
   - Transaction costs
   - Market conditions
   - Fund-specific factors

6. **Use at Your Own Risk**: The authors assume no liability for investment decisions made based on this tool's output.

## Technical Details

### Data Source
- **Provider**: Stooq.pl
- **Update Frequency**: Daily (depends on fund)
- **Historical Data**: Varies by fund (some have years, others months)

### Calculations
- **Trading Days**: 252 per year assumed
- **Risk-Free Rate**: 5% annual (configurable in code)
- **Return Periods**:
  - 1 month = 21 trading days
  - 3 months = 63 trading days
  - 6 months = 126 trading days
  - 1 year = 252 trading days

### Architecture
- **Language**: Python 3.8+
- **Concurrency**: ThreadPoolExecutor for parallel downloads
- **Caching**: Pickle-based file cache
- **Data Processing**: Pandas and NumPy
- **Statistics**: SciPy
- **Visualization**: Matplotlib and Seaborn

## Contributing

Contributions are welcome! Areas for improvement:
- Additional metrics (alpha, beta, information ratio)
- Benchmark comparison (e.g., WIG20 index)
- Sector/category analysis
- Machine learning models
- Interactive dashboards
- Real-time updates

## License

This project is provided as-is for educational purposes. Please review the license file if included.

## Support

For issues, questions, or suggestions:
1. Check this README
2. Review command-line help: `python analyze_polish_funds.py --help`
3. Examine the code documentation
4. Open an issue in the repository

## Changelog

### Version 2.0 (Enhanced)
- ✨ Added risk-adjusted return metrics (Sharpe, Sortino, Calmar)
- ✨ Added statistical analysis (skewness, kurtosis, VaR)
- ✨ Implemented parallel processing for better performance
- ✨ Added smart caching mechanism
- ✨ Multiple export formats (CSV, Excel, JSON, HTML)
- ✨ Visualization support with charts and plots
- ✨ Multi-factor scoring system
- ✨ Configurable recommendation weights
- ✨ Progress bars for better UX
- 📊 Enhanced output with percentile rankings
- 🐛 Improved error handling and retries
- 📝 Comprehensive documentation

### Version 1.0 (Original)
- Basic return calculations (1m, 6m, 1y)
- Simple Buy/Hold/Sell recommendations
- CSV output
- Sequential processing

---

**Happy Analyzing! 📈📊**

*Remember: This tool helps analyze data, but investment decisions should always involve professional advice and thorough personal research.*

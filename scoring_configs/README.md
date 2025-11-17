# Scoring Configuration Files

This directory contains predefined scoring configurations for the Polish Funds Analyzer.

## Available Configurations

### 1. Balanced (Default)
**File**: `balanced.json`

Equal emphasis on returns and risk metrics. This is the default configuration used when no custom config is specified.

**Weights**:
- Returns: 45% (6m: 25%, 1y: 20%)
- Risk-adjusted: 55% (Sharpe: 25%, Sortino: 15%, Max DD: 15%)

**Best for**: Most investors seeking a balanced approach

**Usage**:
```bash
python analyze_polish_funds.py --score-config scoring_configs/balanced.json
```

### 2. Conservative
**File**: `conservative.json`

Emphasizes risk management and capital preservation over high returns.

**Weights**:
- Returns: 30% (6m: 15%, 1y: 15%)
- Risk-adjusted: 70% (Sharpe: 20%, Sortino: 20%, Max DD: 30%)

**Best for**: Risk-averse investors, those nearing retirement, or in volatile markets

**Usage**:
```bash
python analyze_polish_funds.py --score-config scoring_configs/conservative.json
```

### 3. Aggressive
**File**: `aggressive.json`

Prioritizes high returns with less concern for volatility or drawdowns.

**Weights**:
- Returns: 70% (6m: 35%, 1y: 35%)
- Risk-adjusted: 30% (Sharpe: 15%, Sortino: 10%, Max DD: 5%)

**Best for**: Young investors, long time horizons, growth-focused portfolios

**Usage**:
```bash
python analyze_polish_funds.py --score-config scoring_configs/aggressive.json
```

## Creating Custom Configurations

You can create your own scoring configuration by following this template:

```json
{
  "description": "Your strategy description",
  "weights": {
    "return_6m": 0.25,
    "return_1y": 0.20,
    "sharpe_ratio": 0.25,
    "sortino_ratio": 0.15,
    "max_drawdown": 0.15
  },
  "comment": "Optional comment explaining your strategy"
}
```

### Rules for Custom Configurations

1. **All weights must sum to 1.0** (100%)
2. **All weights must be between 0 and 1**
3. **Required keys**:
   - `return_6m`: Weight for 6-month returns
   - `return_1y`: Weight for 1-year returns
   - `sharpe_ratio`: Weight for Sharpe ratio
   - `sortino_ratio`: Weight for Sortino ratio
   - `max_drawdown`: Weight for maximum drawdown
4. **Optional keys**:
   - `description`: Human-readable description
   - `comment`: Additional notes

### Example Custom Configs

**Momentum-Focused** (Recent performance):
```json
{
  "weights": {
    "return_6m": 0.50,
    "return_1y": 0.10,
    "sharpe_ratio": 0.20,
    "sortino_ratio": 0.10,
    "max_drawdown": 0.10
  }
}
```

**Quality-Focused** (Risk-adjusted returns):
```json
{
  "weights": {
    "return_6m": 0.10,
    "return_1y": 0.10,
    "sharpe_ratio": 0.40,
    "sortino_ratio": 0.30,
    "max_drawdown": 0.10
  }
}
```

**Stability-Focused** (Low drawdown):
```json
{
  "weights": {
    "return_6m": 0.15,
    "return_1y": 0.15,
    "sharpe_ratio": 0.15,
    "sortino_ratio": 0.15,
    "max_drawdown": 0.40
  }
}
```

## Understanding the Metrics

### Return Metrics
- **return_6m**: Recent performance indicator, captures momentum
- **return_1y**: Longer-term performance, less affected by short-term volatility

### Risk-Adjusted Metrics
- **sharpe_ratio**: Reward per unit of total risk (volatility)
- **sortino_ratio**: Reward per unit of downside risk (better for asymmetric returns)
- **max_drawdown**: Worst peak-to-trough decline (capital preservation)

## Strategy Selection Guide

### Choose **Conservative** if:
- ✓ You have low risk tolerance
- ✓ You're nearing retirement or need income soon
- ✓ You want to preserve capital
- ✓ Markets are highly volatile
- ✓ You prefer steady, predictable growth

### Choose **Balanced** if:
- ✓ You want a mix of growth and safety
- ✓ You have moderate risk tolerance
- ✓ You're unsure which strategy fits best
- ✓ You want the "standard" approach
- ✓ You have a medium-term investment horizon (5-10 years)

### Choose **Aggressive** if:
- ✓ You have high risk tolerance
- ✓ You have a long time horizon (10+ years)
- ✓ You can withstand significant drawdowns
- ✓ You're seeking maximum growth
- ✓ You can emotionally handle volatility

## Comparing Strategies

Run the analyzer with different configs to compare:

```bash
# Conservative approach
python analyze_polish_funds.py --score-config scoring_configs/conservative.json \
    --output results_conservative

# Balanced approach
python analyze_polish_funds.py --score-config scoring_configs/balanced.json \
    --output results_balanced

# Aggressive approach
python analyze_polish_funds.py --score-config scoring_configs/aggressive.json \
    --output results_aggressive
```

Then compare the top recommendations from each strategy to see how they differ!

## Tips

1. **Test multiple strategies**: Different market conditions favor different approaches
2. **Combine with personal research**: Use scores as a starting point, not the final decision
3. **Consider your goals**: Align the strategy with your investment objectives
4. **Review periodically**: Your optimal strategy may change as you age or circumstances change
5. **Diversify**: Don't rely solely on one fund, even if it scores highest

## Disclaimer

These configurations are examples only and do not constitute investment advice. Your optimal strategy depends on your personal financial situation, goals, and risk tolerance. Consult a financial advisor for personalized guidance.

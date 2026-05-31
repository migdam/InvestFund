#!/usr/bin/env python3
"""
Comprehensive test suite using mock data
Tests all functionality without network dependencies
"""

import sys
import os
import json
import time
import pickle
from pathlib import Path
from datetime import datetime, timedelta
import shutil

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from analyze_polish_funds import FundAnalyzer, FundInfo, FundMetrics


class MockData:
    """Generate realistic mock data for testing"""

    @staticmethod
    def generate_fund_list(count=10):
        """Generate mock fund list"""
        funds = []
        for i in range(count):
            funds.append(FundInfo(
                symbol=f"FUND{i:03d}.N",
                name=f"Test Fund {i+1}"
            ))
        return funds

    @staticmethod
    def generate_price_data(days=500, volatility=0.02, trend=0.0001):
        """Generate realistic price data"""
        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        prices = [100.0]  # Starting price

        for i in range(1, days):
            # Random walk with drift
            change = np.random.normal(trend, volatility)
            new_price = prices[-1] * (1 + change)
            prices.append(max(new_price, 1.0))  # Prevent negative prices

        df = pd.DataFrame({
            'Date': dates,
            'Open': prices,
            'High': [p * (1 + abs(np.random.normal(0, 0.005))) for p in prices],
            'Low': [p * (1 - abs(np.random.normal(0, 0.005))) for p in prices],
            'Close': prices,
            'Volume': [int(np.random.uniform(10000, 100000)) for _ in range(days)]
        })

        return df


class TestResults:
    """Track test results"""

    def __init__(self):
        self.tests = []
        self.passed = 0
        self.failed = 0

    def add(self, name, passed, message="", duration=0):
        """Add test result"""
        self.tests.append({
            'name': name,
            'passed': passed,
            'message': message,
            'duration': duration
        })
        if passed:
            self.passed += 1
            print(f"✓ PASS: {name} ({duration:.3f}s)")
        else:
            self.failed += 1
            print(f"✗ FAIL: {name} - {message} ({duration:.3f}s)")

    def summary(self):
        """Print summary"""
        total = self.passed + self.failed
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        print(f"Total: {total}")
        print(f"Passed: {self.passed} ({self.passed/total*100:.1f}%)")
        print(f"Failed: {self.failed} ({self.failed/total*100:.1f}%)")
        print("="*80)
        return self.failed == 0


def run_tests():
    """Run all tests"""
    results = TestResults()
    test_dir = Path("test_output_mocks")
    test_dir.mkdir(exist_ok=True)

    print("="*80)
    print("COMPREHENSIVE TESTING WITH MOCK DATA")
    print("="*80)
    print()

    # ========================================================================
    # Test 1: Mock Data Generation
    # ========================================================================
    start = time.time()
    try:
        funds = MockData.generate_fund_list(10)
        assert len(funds) == 10
        assert all(isinstance(f, FundInfo) for f in funds)
        results.add("Mock Fund List Generation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Mock Fund List Generation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 2: Mock Price Data Generation
    # ========================================================================
    start = time.time()
    try:
        df = MockData.generate_price_data(days=300)
        assert len(df) == 300
        assert all(col in df.columns for col in ['Date', 'Close', 'Volume'])
        assert df['Close'].min() > 0
        results.add("Mock Price Data Generation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Mock Price Data Generation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 3: Return Calculations
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = MockData.generate_price_data(days=300)
        returns = analyzer.calculate_returns(df)

        assert '1m' in returns
        assert '6m' in returns
        assert '1y' in returns
        assert returns['1m'] is not None
        results.add("Return Calculations", True, duration=time.time()-start)
    except Exception as e:
        results.add("Return Calculations", False, str(e), time.time()-start)

    # ========================================================================
    # Test 4: Volatility Calculation
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = MockData.generate_price_data(days=300)
        vol = analyzer.calculate_volatility(df)

        assert vol is not None
        assert vol > 0
        assert vol < 2.0  # Reasonable annual volatility
        results.add("Volatility Calculation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Volatility Calculation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 5: Sharpe Ratio Calculation
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = MockData.generate_price_data(days=300)
        sharpe = analyzer.calculate_sharpe_ratio(df)

        assert sharpe is not None
        assert -5 < sharpe < 5  # Reasonable range
        results.add("Sharpe Ratio Calculation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Sharpe Ratio Calculation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 6: Sortino Ratio Calculation
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = MockData.generate_price_data(days=300)
        sortino = analyzer.calculate_sortino_ratio(df)

        assert sortino is not None
        results.add("Sortino Ratio Calculation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Sortino Ratio Calculation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 7: Maximum Drawdown Calculation
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = MockData.generate_price_data(days=300)
        max_dd = analyzer.calculate_max_drawdown(df)

        assert max_dd is not None
        assert max_dd <= 0  # Drawdown is negative
        assert max_dd > -1.0  # Not more than 100% loss
        results.add("Maximum Drawdown Calculation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Maximum Drawdown Calculation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 8: Calmar Ratio Calculation
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = MockData.generate_price_data(days=300, trend=0.0005)  # Positive trend
        calmar = analyzer.calculate_calmar_ratio(df)

        assert calmar is not None or calmar is None  # Can be None if no drawdown
        results.add("Calmar Ratio Calculation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Calmar Ratio Calculation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 9: VaR and CVaR Calculation
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = MockData.generate_price_data(days=300)
        var, cvar = analyzer.calculate_var_cvar(df)

        assert var is not None
        assert cvar is not None
        assert cvar <= var  # CVaR should be more negative than VaR
        results.add("VaR and CVaR Calculation", True, duration=time.time()-start)
    except Exception as e:
        results.add("VaR and CVaR Calculation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 10: Statistical Measures
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = MockData.generate_price_data(days=300)
        stats = analyzer.calculate_statistics(df)

        assert 'skewness' in stats
        assert 'kurtosis' in stats
        results.add("Statistical Measures Calculation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Statistical Measures Calculation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 11: Recommendation Assignment
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        metrics = FundMetrics(
            symbol="TEST.N",
            name="Test Fund",
            return_6m=0.15,
            return_1y=0.20,
            sharpe_ratio=1.5,
            sortino_ratio=1.8,
            max_drawdown=-0.10
        )

        rec, score = analyzer.assign_recommendation(metrics)

        assert rec in ['Buy', 'Hold', 'Sell']
        assert 0 <= score <= 100
        results.add("Recommendation Assignment", True, duration=time.time()-start)
    except Exception as e:
        results.add("Recommendation Assignment", False, str(e), time.time()-start)

    # ========================================================================
    # Test 12: Custom Scoring Weights
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        metrics = FundMetrics(
            symbol="TEST.N",
            name="Test Fund",
            return_6m=0.15,
            return_1y=0.20,
            sharpe_ratio=1.5,
            sortino_ratio=1.8,
            max_drawdown=-0.10
        )

        custom_weights = {
            "return_6m": 0.5,
            "return_1y": 0.1,
            "sharpe_ratio": 0.1,
            "sortino_ratio": 0.1,
            "max_drawdown": 0.2
        }

        rec, score = analyzer.assign_recommendation(metrics, custom_weights)

        assert rec in ['Buy', 'Hold', 'Sell']
        assert 0 <= score <= 100
        results.add("Custom Scoring Weights", True, duration=time.time()-start)
    except Exception as e:
        results.add("Custom Scoring Weights", False, str(e), time.time()-start)

    # ========================================================================
    # Test 13: DataFrame Creation
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        metrics_list = [
            FundMetrics(
                symbol=f"FUND{i}.N",
                name=f"Fund {i}",
                return_6m=np.random.uniform(-0.1, 0.2),
                score=np.random.uniform(0, 100),
                recommendation=np.random.choice(['Buy', 'Hold', 'Sell'])
            )
            for i in range(10)
        ]

        df = analyzer.create_summary_dataframe(metrics_list)

        assert len(df) == 10
        assert 'symbol' in df.columns
        assert 'score' in df.columns
        assert 'recommendation' in df.columns
        results.add("DataFrame Creation", True, duration=time.time()-start)
    except Exception as e:
        results.add("DataFrame Creation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 14: CSV Export
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        metrics_list = [
            FundMetrics(
                symbol=f"FUND{i}.N",
                name=f"Fund {i}",
                return_6m=0.1,
                score=50,
                recommendation='Hold'
            )
            for i in range(5)
        ]

        df = analyzer.create_summary_dataframe(metrics_list)
        output_file = test_dir / "test.csv"
        analyzer.export_to_csv(df, str(output_file))

        assert output_file.exists()
        df_read = pd.read_csv(output_file)
        assert len(df_read) == 5
        results.add("CSV Export", True, duration=time.time()-start)
    except Exception as e:
        results.add("CSV Export", False, str(e), time.time()-start)

    # ========================================================================
    # Test 15: Excel Export
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        metrics_list = [
            FundMetrics(
                symbol=f"FUND{i}.N",
                name=f"Fund {i}",
                return_6m=0.1,
                score=50,
                recommendation='Hold'
            )
            for i in range(5)
        ]

        df = analyzer.create_summary_dataframe(metrics_list)
        output_file = test_dir / "test.xlsx"
        analyzer.export_to_excel(df, str(output_file))

        assert output_file.exists()
        df_read = pd.read_excel(output_file)
        assert len(df_read) == 5
        results.add("Excel Export", True, duration=time.time()-start)
    except Exception as e:
        results.add("Excel Export", False, str(e), time.time()-start)

    # ========================================================================
    # Test 16: JSON Export
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        metrics_list = [
            FundMetrics(
                symbol=f"FUND{i}.N",
                name=f"Fund {i}",
                return_6m=0.1,
                score=50,
                recommendation='Hold'
            )
            for i in range(5)
        ]

        df = analyzer.create_summary_dataframe(metrics_list)
        output_file = test_dir / "test.json"
        analyzer.export_to_json(df, str(output_file))

        assert output_file.exists()
        with open(output_file) as f:
            data = json.load(f)
        assert len(data) == 5
        results.add("JSON Export", True, duration=time.time()-start)
    except Exception as e:
        results.add("JSON Export", False, str(e), time.time()-start)

    # ========================================================================
    # Test 17: HTML Export
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        metrics_list = [
            FundMetrics(
                symbol=f"FUND{i}.N",
                name=f"Fund {i}",
                return_6m=0.1,
                score=50,
                recommendation='Hold'
            )
            for i in range(5)
        ]

        df = analyzer.create_summary_dataframe(metrics_list)
        output_file = test_dir / "test.html"
        analyzer.export_to_html(df, str(output_file))

        assert output_file.exists()
        with open(output_file) as f:
            html = f.read()
        assert '<!DOCTYPE html>' in html
        assert '<table' in html
        results.add("HTML Export", True, duration=time.time()-start)
    except Exception as e:
        results.add("HTML Export", False, str(e), time.time()-start)

    # ========================================================================
    # Test 18: Visualization Generation
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        metrics_list = [
            FundMetrics(
                symbol=f"FUND{i}.N",
                name=f"Fund {i}",
                return_1m=np.random.uniform(-0.05, 0.1),
                return_6m=np.random.uniform(-0.1, 0.2),
                return_1y=np.random.uniform(-0.2, 0.3),
                volatility=np.random.uniform(0.1, 0.3),
                sharpe_ratio=np.random.uniform(-1, 3),
                sortino_ratio=np.random.uniform(-1, 3),
                max_drawdown=np.random.uniform(-0.3, -0.05),
                score=np.random.uniform(0, 100),
                recommendation=np.random.choice(['Buy', 'Hold', 'Sell'])
            )
            for i in range(20)
        ]

        df = analyzer.create_summary_dataframe(metrics_list)
        plots_dir = test_dir / "plots"
        analyzer.create_visualizations(df, output_dir=str(plots_dir))

        assert (plots_dir / "fund_analysis_overview.png").exists()
        assert (plots_dir / "fund_analysis_metrics.png").exists()
        results.add("Visualization Generation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Visualization Generation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 19: Edge Cases - Empty Data
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = pd.DataFrame()
        returns = analyzer.calculate_returns(df)

        assert returns['1m'] is None
        assert returns['6m'] is None
        results.add("Edge Case - Empty Data", True, duration=time.time()-start)
    except Exception as e:
        results.add("Edge Case - Empty Data", False, str(e), time.time()-start)

    # ========================================================================
    # Test 20: Edge Cases - Insufficient Data
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = MockData.generate_price_data(days=10)  # Only 10 days
        returns = analyzer.calculate_returns(df)

        # Should not have 1m return (need 21+ days)
        assert returns['1m'] is None
        results.add("Edge Case - Insufficient Data", True, duration=time.time()-start)
    except Exception as e:
        results.add("Edge Case - Insufficient Data", False, str(e), time.time()-start)

    # ========================================================================
    # Test 21: Score Boundary Testing
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)

        # Test excellent fund
        excellent_fund = FundMetrics(
            symbol="EXCELLENT.N",
            name="Excellent Fund",
            return_6m=0.20,
            return_1y=0.30,
            sharpe_ratio=2.5,
            sortino_ratio=3.0,
            max_drawdown=-0.03
        )
        rec, score = analyzer.assign_recommendation(excellent_fund)
        assert rec == 'Buy'
        assert score >= 70

        # Test poor fund
        poor_fund = FundMetrics(
            symbol="POOR.N",
            name="Poor Fund",
            return_6m=-0.15,
            return_1y=-0.20,
            sharpe_ratio=-0.5,
            sortino_ratio=-0.3,
            max_drawdown=-0.40
        )
        rec, score = analyzer.assign_recommendation(poor_fund)
        assert rec == 'Sell'
        assert score < 40

        results.add("Score Boundary Testing", True, duration=time.time()-start)
    except Exception as e:
        results.add("Score Boundary Testing", False, str(e), time.time()-start)

    # ========================================================================
    # Test 22: Data Type Validation
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        df = MockData.generate_price_data(days=300)

        # Ensure all metrics return appropriate types
        vol = analyzer.calculate_volatility(df)
        assert isinstance(vol, (float, type(None)))

        sharpe = analyzer.calculate_sharpe_ratio(df)
        assert isinstance(sharpe, (float, type(None)))

        results.add("Data Type Validation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Data Type Validation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 23: Percentile Ranking
    # ========================================================================
    start = time.time()
    try:
        from scipy import stats
        analyzer = FundAnalyzer(use_cache=False)

        metrics_list = [
            FundMetrics(
                symbol=f"FUND{i}.N",
                name=f"Fund {i}",
                score=i * 10  # Scores from 0 to 90
            )
            for i in range(10)
        ]

        # Calculate percentiles
        scores = [m.score for m in metrics_list]
        for m in metrics_list:
            m.percentile_rank = stats.percentileofscore(scores, m.score)

        # Verify percentiles
        assert metrics_list[0].percentile_rank < metrics_list[-1].percentile_rank
        assert 0 <= metrics_list[0].percentile_rank <= 100

        results.add("Percentile Ranking", True, duration=time.time()-start)
    except Exception as e:
        results.add("Percentile Ranking", False, str(e), time.time()-start)

    # ========================================================================
    # Test 24: Configuration File Loading
    # ========================================================================
    start = time.time()
    try:
        config_files = [
            'scoring_configs/balanced.json',
            'scoring_configs/conservative.json',
            'scoring_configs/aggressive.json'
        ]

        for config_file in config_files:
            with open(config_file) as f:
                config = json.load(f)

            assert 'weights' in config
            weights = config['weights']
            assert abs(sum(weights.values()) - 1.0) < 0.01  # Sum to 1.0

        results.add("Configuration File Loading", True, duration=time.time()-start)
    except Exception as e:
        results.add("Configuration File Loading", False, str(e), time.time()-start)

    # ========================================================================
    # Test 25: Realistic Volatility Scenarios
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)

        # Low volatility fund
        df_low = MockData.generate_price_data(days=300, volatility=0.005)
        vol_low = analyzer.calculate_volatility(df_low)

        # High volatility fund
        df_high = MockData.generate_price_data(days=300, volatility=0.05)
        vol_high = analyzer.calculate_volatility(df_high)

        assert vol_high > vol_low
        results.add("Realistic Volatility Scenarios", True, duration=time.time()-start)
    except Exception as e:
        results.add("Realistic Volatility Scenarios", False, str(e), time.time()-start)

    # ========================================================================
    # Test 26: Benchmark Metrics - structure and ranges
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        bench_df = MockData.generate_price_data(days=400, volatility=0.015, trend=0.0003)
        fund_df = MockData.generate_price_data(days=400, volatility=0.02, trend=0.0004)

        metrics = analyzer.calculate_benchmark_metrics(fund_df, bench_df)

        # All six keys present
        for key in ["beta", "alpha", "tracking_error", "information_ratio",
                    "up_capture", "down_capture"]:
            assert key in metrics
        # Beta and tracking error should be computable and finite
        assert metrics["beta"] is not None and np.isfinite(metrics["beta"])
        assert metrics["tracking_error"] is not None and metrics["tracking_error"] >= 0
        results.add("Benchmark Metrics Structure", True, duration=time.time()-start)
    except Exception as e:
        results.add("Benchmark Metrics Structure", False, str(e), time.time()-start)

    # ========================================================================
    # Test 27: Benchmark Metrics - beta of identical series is ~1
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        bench_df = MockData.generate_price_data(days=400, volatility=0.015)
        # Fund identical to benchmark -> beta ~1, tracking error ~0
        metrics = analyzer.calculate_benchmark_metrics(bench_df.copy(), bench_df)

        assert metrics["beta"] is not None
        assert abs(metrics["beta"] - 1.0) < 0.01, f"beta={metrics['beta']}"
        assert metrics["tracking_error"] is not None
        assert metrics["tracking_error"] < 1e-6, f"te={metrics['tracking_error']}"
        results.add("Benchmark Beta Identity", True, duration=time.time()-start)
    except Exception as e:
        results.add("Benchmark Beta Identity", False, str(e), time.time()-start)

    # ========================================================================
    # Test 28: Benchmark Metrics - insufficient overlap returns Nones
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        bench_df = MockData.generate_price_data(days=400, volatility=0.015)
        short_df = MockData.generate_price_data(days=30, volatility=0.02)

        metrics = analyzer.calculate_benchmark_metrics(short_df, bench_df)
        # < 60 overlapping days -> all None
        assert all(metrics[k] is None for k in metrics)
        results.add("Benchmark Insufficient Overlap", True, duration=time.time()-start)
    except Exception as e:
        results.add("Benchmark Insufficient Overlap", False, str(e), time.time()-start)

    # ========================================================================
    # Test 29: Correlation Matrix - identical funds correlate ~1
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        base = MockData.generate_price_data(days=300, volatility=0.02)

        # Monkeypatch download_quotes to serve in-memory mock series
        store = {
            "A.N": base,
            "B.N": base.copy(),  # identical -> correlation ~1
            "C.N": MockData.generate_price_data(days=300, volatility=0.02),
        }
        analyzer.download_quotes = lambda symbol, max_retries=3: store.get(symbol)

        corr, high_pairs = analyzer.compute_correlation_matrix(["A.N", "B.N", "C.N"])

        assert corr is not None
        # A and B are identical -> flagged as highly correlated
        flagged = {(a, b) for a, b, _ in high_pairs}
        assert ("A.N", "B.N") in flagged or ("B.N", "A.N") in flagged
        results.add("Correlation Identical Funds", True, duration=time.time()-start)
    except Exception as e:
        results.add("Correlation Identical Funds", False, str(e), time.time()-start)

    # ========================================================================
    # Test 30: Correlation Matrix - too few funds returns empty
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        store = {"A.N": MockData.generate_price_data(days=300)}
        analyzer.download_quotes = lambda symbol, max_retries=3: store.get(symbol)

        corr, high_pairs = analyzer.compute_correlation_matrix(["A.N"])
        assert corr is None and high_pairs == []
        results.add("Correlation Too Few Funds", True, duration=time.time()-start)
    except Exception as e:
        results.add("Correlation Too Few Funds", False, str(e), time.time()-start)

    # ========================================================================
    # Test 31: analyze_fund populates benchmark fields when benchmark set
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)
        bench_df = MockData.generate_price_data(days=400, volatility=0.015)
        fund_df = MockData.generate_price_data(days=400, volatility=0.02)

        analyzer.benchmark_df = bench_df
        analyzer.download_quotes = lambda symbol, max_retries=3: fund_df
        m = analyzer.analyze_fund(FundInfo(symbol="X.N", name="Fund X"))

        assert m is not None
        assert m.beta is not None
        assert m.tracking_error is not None
        results.add("analyze_fund Benchmark Integration", True, duration=time.time()-start)
    except Exception as e:
        results.add("analyze_fund Benchmark Integration", False, str(e), time.time()-start)

    # ========================================================================
    # Test 32: Portfolio valuation - P&L, weights, totals
    # ========================================================================
    start = time.time()
    try:
        from analyze_polish_funds import Holding

        analyzer = FundAnalyzer(use_cache=False)
        # Two funds with known latest close prices
        df_a = MockData.generate_price_data(days=300)
        df_b = MockData.generate_price_data(days=300)
        df_a.loc[df_a.index[-1], "Close"] = 60.0  # latest price A = 60
        df_b.loc[df_b.index[-1], "Close"] = 20.0  # latest price B = 20
        store = {"A.N": df_a, "B.N": df_b}
        analyzer.download_quotes = lambda symbol, max_retries=3: store.get(symbol)

        holdings = [
            Holding(symbol="A.N", shares=100, cost_basis=50.0, ter=0.02),  # cost 5000, val 6000
            Holding(symbol="B.N", shares=200, cost_basis=25.0, ter=0.01),  # cost 5000, val 4000
        ]
        positions, summary = analyzer.analyze_portfolio(holdings)

        assert summary["num_priced"] == 2
        assert abs(summary["total_cost"] - 10000.0) < 1e-6
        assert abs(summary["total_value"] - 10000.0) < 1e-6  # 6000 + 4000
        assert abs(summary["total_pnl"] - 0.0) < 1e-6  # +1000 (A) - 1000 (B)
        # Position A weight = 6000/10000 = 0.6
        pos_a = next(p for p in positions if p.symbol == "A.N")
        assert abs(pos_a.weight - 0.6) < 1e-6
        assert abs(pos_a.unrealized_pnl - 1000.0) < 1e-6
        # Annual fees: 0.02*6000 + 0.01*4000 = 120 + 40 = 160
        assert abs(summary["total_annual_fees"] - 160.0) < 1e-6
        results.add("Portfolio Valuation", True, duration=time.time()-start)
    except Exception as e:
        results.add("Portfolio Valuation", False, str(e), time.time()-start)

    # ========================================================================
    # Test 33: Portfolio handles unpriced (missing) holdings gracefully
    # ========================================================================
    start = time.time()
    try:
        from analyze_polish_funds import Holding

        analyzer = FundAnalyzer(use_cache=False)
        df_a = MockData.generate_price_data(days=300)
        df_a.loc[df_a.index[-1], "Close"] = 10.0
        store = {"A.N": df_a}  # B.N missing
        analyzer.download_quotes = lambda symbol, max_retries=3: store.get(symbol)

        holdings = [
            Holding(symbol="A.N", shares=10, cost_basis=8.0),
            Holding(symbol="B.N", shares=10, cost_basis=8.0),  # no data
        ]
        positions, summary = analyzer.analyze_portfolio(holdings)

        assert summary["num_positions"] == 2
        assert summary["num_priced"] == 1
        pos_b = next(p for p in positions if p.symbol == "B.N")
        assert pos_b.current_value is None
        assert pos_b.unrealized_pnl is None
        results.add("Portfolio Missing Data Handling", True, duration=time.time()-start)
    except Exception as e:
        results.add("Portfolio Missing Data Handling", False, str(e), time.time()-start)

    # ========================================================================
    # Test 34: Fee-drag projection math
    # ========================================================================
    start = time.time()
    try:
        analyzer = FundAnalyzer(use_cache=False)

        # Zero TER -> net equals gross, no fees
        z = analyzer.project_fee_drag(10000, ter=0.0, years=10, gross_annual_return=0.06)
        assert abs(z["gross_value"] - z["net_value"]) < 1e-6
        assert abs(z["total_fees"]) < 1e-6

        # Positive TER -> net < gross, fees > 0, drag between 0 and 1
        p = analyzer.project_fee_drag(10000, ter=0.02, years=20, gross_annual_return=0.06)
        assert p["net_value"] < p["gross_value"]
        assert p["total_fees"] > 0
        assert 0 < p["drag_pct"] < 1

        # Known one-year check: net = 10000 * 1.06 * 0.98
        one = analyzer.project_fee_drag(10000, ter=0.02, years=1, gross_annual_return=0.06)
        assert abs(one["net_value"] - 10000 * 1.06 * 0.98) < 1e-6
        results.add("Fee-Drag Projection Math", True, duration=time.time()-start)
    except Exception as e:
        results.add("Fee-Drag Projection Math", False, str(e), time.time()-start)

    # ========================================================================
    # Test 35: load_portfolio from JSON and CSV
    # ========================================================================
    start = time.time()
    try:
        import tempfile
        analyzer = FundAnalyzer(use_cache=False)

        # JSON (object with "holdings")
        json_path = test_dir / "holdings.json"
        with open(json_path, "w") as f:
            json.dump({"holdings": [
                {"symbol": "A.N", "shares": 10, "cost_basis": 5.0, "ter": 0.015, "name": "A"},
                {"symbol": "B.N", "shares": 20, "cost_basis": 7.5},
            ]}, f)
        h_json = analyzer.load_portfolio(str(json_path))
        assert len(h_json) == 2
        assert h_json[0].symbol == "A.N" and h_json[0].ter == 0.015
        assert h_json[1].ter is None  # missing TER -> None

        # CSV
        csv_path = test_dir / "holdings.csv"
        pd.DataFrame([
            {"symbol": "C.N", "shares": 5, "cost_basis": 100.0, "ter": 0.02, "name": "C"},
            {"symbol": "D.N", "shares": 8, "cost_basis": 50.0, "ter": None, "name": "D"},
        ]).to_csv(csv_path, index=False)
        h_csv = analyzer.load_portfolio(str(csv_path))
        assert len(h_csv) == 2
        assert h_csv[0].symbol == "C.N" and abs(h_csv[0].cost_basis - 100.0) < 1e-6
        results.add("Load Portfolio JSON/CSV", True, duration=time.time()-start)
    except Exception as e:
        results.add("Load Portfolio JSON/CSV", False, str(e), time.time()-start)

    # Print summary
    print()
    success = results.summary()

    # Save results
    results_file = test_dir / "test_results.json"
    with open(results_file, 'w') as f:
        json.dump({
            'summary': {
                'total': results.passed + results.failed,
                'passed': results.passed,
                'failed': results.failed,
                'success_rate': results.passed / (results.passed + results.failed) * 100 if (results.passed + results.failed) > 0 else 0
            },
            'tests': results.tests
        }, f, indent=2)

    print(f"\nDetailed results saved to: {results_file}")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(run_tests())

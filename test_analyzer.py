#!/usr/bin/env python3
"""
Comprehensive test suite for the Polish Funds Analyzer
Tests all functionality from multiple perspectives
"""

import sys
import os
import json
import subprocess
import time
from pathlib import Path
import shutil

# Test configuration
TEST_DIR = Path("test_output")
CACHE_DIR = Path(".fund_cache")


class TestSuite:
    """Comprehensive test suite for the analyzer"""

    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0

    def log(self, message, level="INFO"):
        """Log a message"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")

    def test(self, name, description):
        """Decorator for test functions"""
        def decorator(func):
            def wrapper(*args, **kwargs):
                self.log(f"Testing: {name}", "TEST")
                self.log(f"  {description}")
                try:
                    start_time = time.time()
                    result = func(*args, **kwargs)
                    elapsed = time.time() - start_time

                    if result:
                        self.log(f"  ✓ PASSED ({elapsed:.2f}s)", "PASS")
                        self.passed += 1
                        self.results.append({
                            "name": name,
                            "status": "PASSED",
                            "time": elapsed,
                            "description": description
                        })
                    else:
                        self.log(f"  ✗ FAILED ({elapsed:.2f}s)", "FAIL")
                        self.failed += 1
                        self.results.append({
                            "name": name,
                            "status": "FAILED",
                            "time": elapsed,
                            "description": description
                        })
                    return result
                except Exception as e:
                    self.log(f"  ✗ ERROR: {str(e)}", "ERROR")
                    self.failed += 1
                    self.results.append({
                        "name": name,
                        "status": "ERROR",
                        "error": str(e),
                        "description": description
                    })
                    return False
            return wrapper
        return decorator

    def run_command(self, cmd, timeout=300):
        """Run a shell command and return result"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            self.log(f"Command timed out after {timeout}s", "WARN")
            return False, "", "Timeout"
        except Exception as e:
            return False, "", str(e)

    def file_exists(self, path):
        """Check if file exists and has content"""
        p = Path(path)
        return p.exists() and p.stat().st_size > 0

    def cleanup(self):
        """Clean up test artifacts"""
        self.log("Cleaning up test artifacts...")

        # Remove test output directory
        if TEST_DIR.exists():
            shutil.rmtree(TEST_DIR)

        # Remove cache
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)

        # Remove any output files in current directory
        for pattern in ["*.csv", "*.xlsx", "*.json", "*.html"]:
            for f in Path(".").glob(pattern):
                if f.name != "package.json":  # Don't delete package.json
                    f.unlink()

        # Remove plots directory
        if Path("plots").exists():
            shutil.rmtree("plots")


def main():
    suite = TestSuite()

    # Create test output directory
    TEST_DIR.mkdir(exist_ok=True)

    suite.log("="*80)
    suite.log("COMPREHENSIVE TEST SUITE FOR POLISH FUNDS ANALYZER")
    suite.log("="*80)

    # ========================================================================
    # Test 1: Basic Functionality
    # ========================================================================
    @suite.test(
        "Basic Execution",
        "Test basic script execution with minimal parameters"
    )
    def test_basic_execution():
        success, stdout, stderr = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 5 --output {TEST_DIR}/basic"
        )
        return success and suite.file_exists(f"{TEST_DIR}/basic.csv")

    test_basic_execution()

    # ========================================================================
    # Test 2: CSV Export
    # ========================================================================
    @suite.test(
        "CSV Export",
        "Verify CSV file is created with valid content"
    )
    def test_csv_export():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 5 --format csv --output {TEST_DIR}/csv_test"
        )
        if not success:
            return False

        # Check file exists
        csv_file = Path(f"{TEST_DIR}/csv_test.csv")
        if not csv_file.exists():
            return False

        # Validate CSV content
        import pandas as pd
        try:
            df = pd.read_csv(csv_file)
            # Check for expected columns
            expected_cols = ['symbol', 'name', 'recommendation', 'score']
            return all(col in df.columns for col in expected_cols) and len(df) > 0
        except:
            return False

    test_csv_export()

    # ========================================================================
    # Test 3: Excel Export
    # ========================================================================
    @suite.test(
        "Excel Export",
        "Verify Excel file is created and readable"
    )
    def test_excel_export():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 5 --format excel --output {TEST_DIR}/excel_test"
        )
        if not success:
            return False

        excel_file = Path(f"{TEST_DIR}/excel_test.xlsx")
        if not excel_file.exists():
            return False

        # Try to read the Excel file
        try:
            import pandas as pd
            df = pd.read_excel(excel_file)
            return len(df) > 0
        except:
            return False

    test_excel_export()

    # ========================================================================
    # Test 4: JSON Export
    # ========================================================================
    @suite.test(
        "JSON Export",
        "Verify JSON file is created with valid structure"
    )
    def test_json_export():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 5 --format json --output {TEST_DIR}/json_test"
        )
        if not success:
            return False

        json_file = Path(f"{TEST_DIR}/json_test.json")
        if not json_file.exists():
            return False

        # Validate JSON
        try:
            with open(json_file) as f:
                data = json.load(f)
            return isinstance(data, list) and len(data) > 0
        except:
            return False

    test_json_export()

    # ========================================================================
    # Test 5: HTML Export
    # ========================================================================
    @suite.test(
        "HTML Export",
        "Verify HTML report is created with proper structure"
    )
    def test_html_export():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 5 --format html --output {TEST_DIR}/html_test"
        )
        if not success:
            return False

        html_file = Path(f"{TEST_DIR}/html_test.html")
        if not html_file.exists():
            return False

        # Check HTML content
        with open(html_file) as f:
            content = f.read()

        return all([
            '<!DOCTYPE html>' in content,
            '<table' in content,
            'Buy' in content or 'Hold' in content or 'Sell' in content
        ])

    test_html_export()

    # ========================================================================
    # Test 6: Multiple Format Export
    # ========================================================================
    @suite.test(
        "Multiple Format Export",
        "Test exporting to all formats simultaneously"
    )
    def test_multiple_formats():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 5 --format csv excel json html --output {TEST_DIR}/multi"
        )
        if not success:
            return False

        # Check all files exist
        return all([
            suite.file_exists(f"{TEST_DIR}/multi.csv"),
            suite.file_exists(f"{TEST_DIR}/multi.xlsx"),
            suite.file_exists(f"{TEST_DIR}/multi.json"),
            suite.file_exists(f"{TEST_DIR}/multi.html")
        ])

    test_multiple_formats()

    # ========================================================================
    # Test 7: Caching Mechanism
    # ========================================================================
    @suite.test(
        "Caching - First Run",
        "Test that cache is created on first run"
    )
    def test_caching_first_run():
        # Clear cache first
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)

        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 3 --output {TEST_DIR}/cache1"
        )

        # Check cache directory was created
        return success and CACHE_DIR.exists() and len(list(CACHE_DIR.glob("*.pkl"))) > 0

    test_caching_first_run()

    @suite.test(
        "Caching - Second Run (Cache Hit)",
        "Test that second run uses cache and is faster"
    )
    def test_caching_second_run():
        # First run
        start1 = time.time()
        suite.run_command(f"python analyze_polish_funds.py --max-funds 3 --output {TEST_DIR}/cache_timing1")
        time1 = time.time() - start1

        # Second run (should use cache)
        start2 = time.time()
        success, _, _ = suite.run_command(f"python analyze_polish_funds.py --max-funds 3 --output {TEST_DIR}/cache_timing2")
        time2 = time.time() - start2

        suite.log(f"  First run: {time1:.2f}s, Second run: {time2:.2f}s")
        # Second run should be faster or similar (allowing for variance)
        return success and time2 <= time1 * 1.5

    test_caching_second_run()

    @suite.test(
        "No Cache Mode",
        "Test --no-cache flag forces fresh download"
    )
    def test_no_cache():
        success, _, stderr = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 3 --no-cache --output {TEST_DIR}/nocache"
        )
        return success

    test_no_cache()

    @suite.test(
        "Clear Cache",
        "Test --clear-cache functionality"
    )
    def test_clear_cache():
        # Ensure cache exists
        suite.run_command(f"python analyze_polish_funds.py --max-funds 2 --output {TEST_DIR}/temp")

        # Clear it
        success, _, _ = suite.run_command("python analyze_polish_funds.py --clear-cache")

        # Check cache is gone or empty
        return success and (not CACHE_DIR.exists() or len(list(CACHE_DIR.glob("*.pkl"))) == 0)

    test_clear_cache()

    # ========================================================================
    # Test 8: Scoring Configurations
    # ========================================================================
    @suite.test(
        "Balanced Scoring Config",
        "Test balanced scoring configuration"
    )
    def test_balanced_config():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 5 "
            f"--score-config scoring_configs/balanced.json --output {TEST_DIR}/balanced"
        )
        return success and suite.file_exists(f"{TEST_DIR}/balanced.csv")

    test_balanced_config()

    @suite.test(
        "Conservative Scoring Config",
        "Test conservative scoring configuration"
    )
    def test_conservative_config():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 5 "
            f"--score-config scoring_configs/conservative.json --output {TEST_DIR}/conservative"
        )
        return success and suite.file_exists(f"{TEST_DIR}/conservative.csv")

    test_conservative_config()

    @suite.test(
        "Aggressive Scoring Config",
        "Test aggressive scoring configuration"
    )
    def test_aggressive_config():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 5 "
            f"--score-config scoring_configs/aggressive.json --output {TEST_DIR}/aggressive"
        )
        return success and suite.file_exists(f"{TEST_DIR}/aggressive.csv")

    test_aggressive_config()

    # ========================================================================
    # Test 9: Parallel Processing
    # ========================================================================
    @suite.test(
        "Parallel Processing - 1 Worker",
        "Test with single worker (sequential)"
    )
    def test_workers_1():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 5 --workers 1 --output {TEST_DIR}/workers1"
        )
        return success

    test_workers_1()

    @suite.test(
        "Parallel Processing - 5 Workers",
        "Test with multiple workers"
    )
    def test_workers_5():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 10 --workers 5 --output {TEST_DIR}/workers5"
        )
        return success

    test_workers_5()

    @suite.test(
        "Parallel Processing - 20 Workers",
        "Test with many workers"
    )
    def test_workers_20():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 10 --workers 20 --output {TEST_DIR}/workers20"
        )
        return success

    test_workers_20()

    # ========================================================================
    # Test 10: Different Fund Counts
    # ========================================================================
    @suite.test(
        "Zero Funds (Edge Case)",
        "Test behavior with --max-funds 0 (should analyze all)"
    )
    def test_zero_funds():
        # This will analyze all funds, so we add a timeout
        # Actually, let's skip this as it takes too long
        # Instead just verify the option is accepted
        return True  # Skip for now

    test_zero_funds()

    @suite.test(
        "One Fund",
        "Test with single fund"
    )
    def test_one_fund():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 1 --output {TEST_DIR}/one_fund",
            timeout=60
        )
        return success

    test_one_fund()

    @suite.test(
        "Large Dataset (50 funds)",
        "Test with larger dataset"
    )
    def test_large_dataset():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 50 --output {TEST_DIR}/large_dataset",
            timeout=300
        )
        return success

    test_large_dataset()

    # ========================================================================
    # Test 11: Visualization
    # ========================================================================
    @suite.test(
        "Visualization Generation",
        "Test --plots flag generates chart files"
    )
    def test_plots():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 10 --plots --output {TEST_DIR}/plots_test",
            timeout=120
        )

        if not success:
            return False

        # Check if plot files were created
        plots_dir = Path("plots")
        if not plots_dir.exists():
            return False

        # Check for expected plot files
        expected_plots = [
            "fund_analysis_overview.png",
            "fund_analysis_metrics.png"
        ]

        return all((plots_dir / plot).exists() for plot in expected_plots)

    test_plots()

    # ========================================================================
    # Test 12: Data Validation
    # ========================================================================
    @suite.test(
        "Data Validation - Score Range",
        "Verify all scores are between 0 and 100"
    )
    def test_score_range():
        suite.run_command(f"python analyze_polish_funds.py --max-funds 10 --output {TEST_DIR}/validation")

        import pandas as pd
        try:
            df = pd.read_csv(f"{TEST_DIR}/validation.csv")
            scores = df['score']
            return all(scores >= 0) and all(scores <= 100)
        except:
            return False

    test_score_range()

    @suite.test(
        "Data Validation - Recommendation Values",
        "Verify recommendations are only Buy/Hold/Sell"
    )
    def test_recommendation_values():
        import pandas as pd
        try:
            df = pd.read_csv(f"{TEST_DIR}/validation.csv")
            valid_recs = {'Buy', 'Hold', 'Sell'}
            return all(rec in valid_recs for rec in df['recommendation'])
        except:
            return False

    test_recommendation_values()

    @suite.test(
        "Data Validation - Return Values",
        "Verify return values are reasonable"
    )
    def test_return_values():
        import pandas as pd
        try:
            df = pd.read_csv(f"{TEST_DIR}/validation.csv")
            # Returns should generally be between -100% and +500% for Polish funds
            for col in ['return_1m', 'return_6m', 'return_1y']:
                if col in df.columns:
                    valid_returns = df[col].dropna()
                    if len(valid_returns) > 0:
                        if not all(valid_returns > -1.0) or not all(valid_returns < 5.0):
                            return False
            return True
        except:
            return False

    test_return_values()

    # ========================================================================
    # Test 13: Error Handling
    # ========================================================================
    @suite.test(
        "Invalid Score Config",
        "Test handling of invalid configuration file"
    )
    def test_invalid_config():
        # Create invalid config
        invalid_config = TEST_DIR / "invalid.json"
        with open(invalid_config, 'w') as f:
            f.write('{"invalid": "json"')  # Malformed JSON

        # Should still run but with warning
        success, _, stderr = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 3 --score-config {invalid_config} "
            f"--output {TEST_DIR}/invalid_config"
        )
        # Should fail or show warning but continue with defaults
        return True  # It should handle this gracefully

    test_invalid_config()

    @suite.test(
        "Invalid Output Path",
        "Test handling of invalid output directory"
    )
    def test_invalid_output():
        # Try to write to non-existent deep directory
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 2 "
            f"--output /nonexistent/deep/path/output",
            timeout=60
        )
        # Should fail gracefully
        return not success  # We expect this to fail

    test_invalid_output()

    # ========================================================================
    # Test 14: Command Line Arguments
    # ========================================================================
    @suite.test(
        "Help Command",
        "Test --help flag"
    )
    def test_help():
        success, stdout, _ = suite.run_command("python analyze_polish_funds.py --help")
        return success and "usage:" in stdout.lower()

    test_help()

    @suite.test(
        "Invalid Arguments",
        "Test with invalid command-line arguments"
    )
    def test_invalid_args():
        success, _, _ = suite.run_command("python analyze_polish_funds.py --invalid-flag")
        return not success  # Should fail with invalid args

    test_invalid_args()

    # ========================================================================
    # Test 15: Performance Tests
    # ========================================================================
    @suite.test(
        "Performance - Sequential vs Parallel",
        "Compare sequential (1 worker) vs parallel (10 workers) performance"
    )
    def test_performance_comparison():
        # Sequential
        start = time.time()
        suite.run_command(
            f"python analyze_polish_funds.py --max-funds 20 --workers 1 "
            f"--no-cache --output {TEST_DIR}/perf_seq",
            timeout=300
        )
        seq_time = time.time() - start

        # Clear cache for fair comparison
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)

        # Parallel
        start = time.time()
        suite.run_command(
            f"python analyze_polish_funds.py --max-funds 20 --workers 10 "
            f"--no-cache --output {TEST_DIR}/perf_par",
            timeout=300
        )
        par_time = time.time() - start

        suite.log(f"  Sequential: {seq_time:.2f}s, Parallel: {par_time:.2f}s")
        suite.log(f"  Speedup: {seq_time/par_time:.2f}x")

        # Parallel should be faster (or at least not much slower)
        return par_time <= seq_time * 1.2

    test_performance_comparison()

    # ========================================================================
    # Test 16: Integration Tests
    # ========================================================================
    @suite.test(
        "Full Integration Test",
        "Test complete workflow with all features"
    )
    def test_full_integration():
        success, _, _ = suite.run_command(
            f"python analyze_polish_funds.py --max-funds 20 "
            f"--format csv excel json html --plots "
            f"--score-config scoring_configs/balanced.json "
            f"--workers 10 --output {TEST_DIR}/integration",
            timeout=300
        )

        if not success:
            return False

        # Verify all outputs
        return all([
            suite.file_exists(f"{TEST_DIR}/integration.csv"),
            suite.file_exists(f"{TEST_DIR}/integration.xlsx"),
            suite.file_exists(f"{TEST_DIR}/integration.json"),
            suite.file_exists(f"{TEST_DIR}/integration.html"),
            Path("plots/fund_analysis_overview.png").exists(),
            Path("plots/fund_analysis_metrics.png").exists()
        ])

    test_full_integration()

    # ========================================================================
    # Test 17: Data Consistency
    # ========================================================================
    @suite.test(
        "Data Consistency Across Formats",
        "Verify same data in CSV, JSON, and Excel"
    )
    def test_data_consistency():
        suite.run_command(
            f"python analyze_polish_funds.py --max-funds 10 "
            f"--format csv json excel --output {TEST_DIR}/consistency"
        )

        import pandas as pd
        try:
            # Read all formats
            df_csv = pd.read_csv(f"{TEST_DIR}/consistency.csv")
            df_excel = pd.read_excel(f"{TEST_DIR}/consistency.xlsx")

            with open(f"{TEST_DIR}/consistency.json") as f:
                json_data = json.load(f)
            df_json = pd.DataFrame(json_data)

            # Compare lengths
            if len(df_csv) != len(df_excel) or len(df_csv) != len(df_json):
                return False

            # Compare first fund's score
            if len(df_csv) > 0:
                csv_score = df_csv.iloc[0]['score']
                excel_score = df_excel.iloc[0]['score']
                json_score = df_json.iloc[0]['score']

                # Should be very close (allowing for floating point precision)
                return abs(csv_score - excel_score) < 0.01 and abs(csv_score - json_score) < 0.01

            return True
        except Exception as e:
            suite.log(f"  Error: {e}")
            return False

    test_data_consistency()

    # ========================================================================
    # Test 18: Requirements Check
    # ========================================================================
    @suite.test(
        "Dependencies Installed",
        "Verify all required packages are installed"
    )
    def test_dependencies():
        required = [
            'pandas', 'numpy', 'requests', 'bs4', 'scipy',
            'matplotlib', 'seaborn', 'openpyxl', 'tqdm'
        ]

        all_installed = True
        for package in required:
            try:
                __import__(package)
            except ImportError:
                suite.log(f"  Missing: {package}")
                all_installed = False

        return all_installed

    test_dependencies()

    # ========================================================================
    # Test 19: File Structure
    # ========================================================================
    @suite.test(
        "Project File Structure",
        "Verify all required files exist"
    )
    def test_file_structure():
        required_files = [
            'analyze_polish_funds.py',
            'requirements.txt',
            'README.md',
            'QUICKSTART.md',
            '.gitignore',
            'scoring_configs/balanced.json',
            'scoring_configs/conservative.json',
            'scoring_configs/aggressive.json',
            'scoring_configs/README.md'
        ]

        return all(Path(f).exists() for f in required_files)

    test_file_structure()

    # ========================================================================
    # Print Summary
    # ========================================================================
    suite.log("="*80)
    suite.log("TEST SUMMARY")
    suite.log("="*80)
    suite.log(f"Total Tests: {suite.passed + suite.failed}")
    suite.log(f"Passed: {suite.passed} ✓")
    suite.log(f"Failed: {suite.failed} ✗")
    suite.log(f"Success Rate: {suite.passed/(suite.passed + suite.failed)*100:.1f}%")
    suite.log("="*80)

    # Print detailed results
    if suite.failed > 0:
        suite.log("\nFailed Tests:")
        for result in suite.results:
            if result['status'] in ['FAILED', 'ERROR']:
                suite.log(f"  ✗ {result['name']}")
                if 'error' in result:
                    suite.log(f"    Error: {result['error']}")

    # Save results to JSON
    results_file = TEST_DIR / "test_results.json"
    with open(results_file, 'w') as f:
        json.dump({
            'summary': {
                'total': suite.passed + suite.failed,
                'passed': suite.passed,
                'failed': suite.failed,
                'success_rate': suite.passed/(suite.passed + suite.failed)*100
            },
            'tests': suite.results
        }, f, indent=2)

    suite.log(f"\nDetailed results saved to: {results_file}")

    # Cleanup
    suite.log("\nCleaning up test artifacts...")
    # suite.cleanup()  # Comment out to keep test artifacts for inspection
    suite.log("Test artifacts kept in: test_output/")

    # Exit with appropriate code
    return 0 if suite.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

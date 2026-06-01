#!/usr/bin/env python3
"""
Code quality and documentation tests
"""

import sys
import ast
import re
from pathlib import Path


class CodeQualityTests:
    """Test code quality and documentation"""

    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0

    def test(self, name, passed, message=""):
        """Record test result"""
        self.results.append({'name': name, 'passed': passed, 'message': message})
        if passed:
            self.passed += 1
            print(f"✓ {name}")
        else:
            self.failed += 1
            print(f"✗ {name}: {message}")

    def summary(self):
        """Print summary"""
        total = self.passed + self.failed
        print("\n" + "="*80)
        print(f"CODE QUALITY TESTS: {self.passed}/{total} passed ({self.passed/total*100:.1f}%)")
        print("="*80)
        return self.failed == 0


def test_code_quality():
    """Run code quality tests"""
    tests = CodeQualityTests()

    print("="*80)
    print("CODE QUALITY AND DOCUMENTATION TESTS")
    print("="*80)
    print()

    # Read the main script
    script_path = Path("analyze_polish_funds.py")
    with open(script_path) as f:
        code = f.read()

    # Parse AST
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        tests.test("Valid Python Syntax", False, str(e))
        return 1

    tests.test("Valid Python Syntax", True)

    # Test 1: Module docstring
    module_docstring = ast.get_docstring(tree)
    tests.test(
        "Module Docstring Exists",
        module_docstring is not None and len(module_docstring) > 100
    )

    # Test 2: Count classes and functions
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

    tests.test(
        "Has Classes",
        len(classes) >= 2,
        f"Found {len(classes)} classes"
    )

    tests.test(
        "Has Functions/Methods",
        len(functions) >= 15,
        f"Found {len(functions)} functions"
    )

    # Test 3: Check for docstrings in classes
    classes_with_docstrings = sum(1 for cls in classes if ast.get_docstring(cls))
    tests.test(
        "Classes Have Docstrings",
        classes_with_docstrings == len(classes),
        f"{classes_with_docstrings}/{len(classes)} classes have docstrings"
    )

    # Test 4: Check for docstrings in functions (at least 80%)
    functions_with_docstrings = sum(1 for func in functions if ast.get_docstring(func))
    docstring_ratio = functions_with_docstrings / len(functions) if functions else 0
    tests.test(
        "Functions Have Docstrings (>80%)",
        docstring_ratio > 0.8,
        f"{functions_with_docstrings}/{len(functions)} ({docstring_ratio*100:.1f}%)"
    )

    # Test 5: Check for type hints
    functions_with_annotations = sum(
        1 for func in functions
        if func.returns or any(arg.annotation for arg in func.args.args)
    )
    annotation_ratio = functions_with_annotations / len(functions) if functions else 0
    tests.test(
        "Type Hints Present (>50%)",
        annotation_ratio > 0.5,
        f"{functions_with_annotations}/{len(functions)} ({annotation_ratio*100:.1f}%)"
    )

    # Test 6: No extremely long functions (>200 lines)
    long_functions = [
        func for func in functions
        if hasattr(func, 'end_lineno') and hasattr(func, 'lineno')
        and (func.end_lineno - func.lineno) > 200
    ]
    tests.test(
        "No Extremely Long Functions",
        len(long_functions) == 0,
        f"Found {len(long_functions)} functions >200 lines"
    )

    # Test 7: Check for comments (heuristic: at least some # comments)
    comment_lines = [line for line in code.split('\n') if line.strip().startswith('#')]
    tests.test(
        "Has Comments",
        len(comment_lines) > 20,
        f"Found {len(comment_lines)} comment lines"
    )

    # Test 8: Check for constants (UPPER_CASE variables)
    constants = re.findall(r'^([A-Z_]{2,})\s*=', code, re.MULTILINE)
    tests.test(
        "Has Constants",
        len(constants) >= 3,
        f"Found {len(constants)} constants"
    )

    # Test 9: Check for error handling (try/except blocks)
    try_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Try)]
    tests.test(
        "Has Error Handling",
        len(try_nodes) >= 5,
        f"Found {len(try_nodes)} try/except blocks"
    )

    # Test 10: Check code structure - has if __name__ == "__main__"
    has_main_guard = 'if __name__ == "__main__"' in code
    tests.test(
        "Has Main Guard",
        has_main_guard
    )

    # Test 11: Check for imports organization
    import_nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    tests.test(
        "Has Import Statements",
        len(import_nodes) >= 10,
        f"Found {len(import_nodes)} imports"
    )

    # Test 12: Check README exists and has content
    readme_path = Path("README.md")
    readme_content = readme_path.read_text() if readme_path.exists() else ""
    tests.test(
        "README.md Exists and Substantial",
        len(readme_content) > 5000,
        f"README has {len(readme_content)} characters"
    )

    # Test 13: Check QUICKSTART exists
    quickstart_path = Path("QUICKSTART.md")
    tests.test(
        "QUICKSTART.md Exists",
        quickstart_path.exists()
    )

    # Test 14: Check requirements.txt exists and has packages
    req_path = Path("requirements.txt")
    if req_path.exists():
        req_content = req_path.read_text()
        req_lines = [l.strip() for l in req_content.split('\n') if l.strip() and not l.startswith('#')]
        tests.test(
            "requirements.txt Has Packages",
            len(req_lines) >= 8,
            f"Found {len(req_lines)} packages"
        )
    else:
        tests.test("requirements.txt Exists", False)

    # Test 15: Check .gitignore exists
    gitignore_path = Path(".gitignore")
    tests.test(
        ".gitignore Exists",
        gitignore_path.exists()
    )

    # Test 16: Check scoring configs exist
    config_files = [
        "scoring_configs/balanced.json",
        "scoring_configs/conservative.json",
        "scoring_configs/aggressive.json"
    ]
    configs_exist = all(Path(f).exists() for f in config_files)
    tests.test(
        "Scoring Configs Exist",
        configs_exist
    )

    # Test 17: Check for dataclass usage
    dataclass_imports = 'from dataclasses import dataclass' in code or 'import dataclasses' in code
    tests.test(
        "Uses Dataclasses",
        dataclass_imports
    )

    # Test 18: Check for ThreadPoolExecutor (parallel processing)
    has_parallel = 'ThreadPoolExecutor' in code
    tests.test(
        "Implements Parallel Processing",
        has_parallel
    )

    # Test 19: Check for progress bars (tqdm)
    has_progress = 'tqdm' in code
    tests.test(
        "Has Progress Indicators",
        has_progress
    )

    # Test 20: Check for caching implementation
    has_caching = 'cache' in code.lower() and 'pickle' in code
    tests.test(
        "Implements Caching",
        has_caching
    )

    # Test 21: Line count reasonable
    line_count = len(code.split('\n'))
    tests.test(
        "Code Size Reasonable",
        1000 <= line_count <= 3500,
        f"{line_count} lines"
    )

    # Test 22: Check for argparse (CLI)
    has_argparse = 'argparse' in code
    tests.test(
        "Implements CLI Arguments",
        has_argparse
    )

    # Test 23: Check for multiple export formats
    export_methods = ['export_to_csv', 'export_to_excel', 'export_to_json', 'export_to_html']
    has_exports = all(method in code for method in export_methods)
    tests.test(
        "Implements Multiple Export Formats",
        has_exports
    )

    # Test 24: Check for visualization
    has_viz = 'matplotlib' in code and 'create_visualizations' in code
    tests.test(
        "Implements Visualization",
        has_viz
    )

    # Test 25: Check for financial metrics
    metrics = ['sharpe_ratio', 'sortino_ratio', 'max_drawdown', 'calmar_ratio']
    has_metrics = all(metric in code for metric in metrics)
    tests.test(
        "Implements Advanced Financial Metrics",
        has_metrics
    )

    return 0 if tests.summary() else 1


if __name__ == "__main__":
    sys.exit(test_code_quality())

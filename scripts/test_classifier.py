"""
scripts/test_classifier.py — Verify task classifier routing decisions
Run without starting the backend:
  python scripts/test_classifier.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from services.task_classifier import task_classifier

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
DIM    = "\033[2m"

# (prompt, expected_type)
TEST_CASES = [
    # Code
    ("Write a Python function to reverse a linked list",                    "code"),
    ("Fix this bug: TypeError: 'NoneType' is not subscriptable",           "code"),
    ("Refactor this class to use async/await",                              "code"),
    ("Write unit tests for my FastAPI endpoint",                            "code"),
    ("Explain this code:\n```python\ndef fib(n): return n if n<2 else fib(n-1)+fib(n-2)\n```", "code"),
    ("Create a REST API in Go with JWT auth",                               "code"),

    # Reasoning
    ("What are the trade-offs between REST and GraphQL for a mobile app?",  "reasoning"),
    ("Plan a microservices architecture for an e-commerce platform",        "reasoning"),
    ("Analyze why my startup failed to gain traction",                      "reasoning"),
    ("Compare PostgreSQL vs MongoDB for a time-series workload",            "reasoning"),
    ("Walk me through the math behind backpropagation",                     "reasoning"),
    ("What strategy should I use for scaling to 1M users?",                "reasoning"),

    # Vision
    ("Describe what's in this image",                                       "vision"),
    ("What does this screenshot show?",                                      "vision"),
    ("OCR the text from this photo",                                        "vision"),
    ("Analyze this diagram.png",                                            "vision"),

    # General
    ("Hello, how are you?",                                                 "general"),
    ("What is the capital of France?",                                      "general"),
    ("Tell me a joke",                                                      "general"),
    ("Summarize the French Revolution",                                     "general"),
]


def run():
    print(f"\n{YELLOW}  JARVIS Classifier Test Suite{RESET}")
    print(f"  {len(TEST_CASES)} test cases\n")
    print(f"  {'PROMPT':<55} {'EXPECTED':<12} {'GOT':<12} {'CONF':<6} STATUS")
    print("  " + "─" * 95)

    passed = failed = 0

    for prompt, expected in TEST_CASES:
        result   = task_classifier.classify_full(prompt)
        got      = result.task_type
        conf     = result.confidence
        ok       = got == expected
        mark     = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
        got_col  = got if ok else f"{RED}{got}{RESET}"
        short    = prompt[:52].replace("\n", " ") + ("…" if len(prompt) > 52 else "")
        print(f"  {short:<55} {expected:<12} {got_col:<12} {conf:<6.2f} {mark}")
        if ok: passed += 1
        else:  failed += 1

    print("  " + "─" * 95)
    color = GREEN if failed == 0 else (YELLOW if failed < 3 else RED)
    print(f"\n  {color}{passed}/{len(TEST_CASES)} passed, {failed} failed{RESET}\n")
    return failed == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)

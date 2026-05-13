"""
backend/services/task_classifier.py — Intelligent prompt classifier
Routes prompts to the right model based on content analysis.

Classification pipeline:
  1. Structural signals (code fences, file paths, stack traces)
  2. Keyword scoring with weighted patterns
  3. Heuristic tie-breaking
  4. Confidence reporting

Task types → models:
  code      → qwen2.5-coder:7b
  reasoning → deepseek-r1:7b
  vision    → llava:7b
  general   → llama3.1:8b
"""

import re
from dataclasses import dataclass, field
from typing import Literal

TaskType = Literal["code", "reasoning", "vision", "general"]


@dataclass
class ClassificationResult:
    task_type: TaskType
    confidence: float           # 0.0 – 1.0
    scores:     dict = field(default_factory=dict)
    signals:    list = field(default_factory=list)


# ── Weighted keyword patterns ─────────────────────────────────
#   (pattern, weight)  — higher weight = stronger signal
CODE_RULES = [
    # Language keywords
    (re.compile(r"\b(def |class |import |from .+ import|async def|await |return |lambda )\b"), 3),
    (re.compile(r"\b(function |const |let |var |=>|async function)\b"), 3),
    (re.compile(r"\b(pub fn|fn |impl |struct |enum |trait |use )\b"), 3),  # Rust
    (re.compile(r"\b(func |package |goroutine)\b"), 3),                    # Go
    # Task verbs
    (re.compile(r"\b(write|create|build|implement|code|script|program|generate)\s+(a|an|the|me)?\s*(function|class|script|api|endpoint|module|component|test)\b", re.I), 4),
    (re.compile(r"\b(debug|fix (the|this|my)|refactor|optimize|review|explain (this|the) code)\b", re.I), 4),
    (re.compile(r"\b(unit test|pytest|jest|mocha|assertion|mock)\b", re.I), 3),
    # Languages named
    (re.compile(r"\b(python|javascript|typescript|rust|golang|c\+\+|java|kotlin|swift|bash|sql|html|css|react|vue|fastapi|django|flask|express)\b", re.I), 2),
    # Syntax characters
    (re.compile(r"[{}\[\]()]{3,}"), 2),   # lots of brackets
    (re.compile(r"\b(api|service|app|backend|server|program|tool)\s+(in|with|using)\s+(go|golang|rust|java|kotlin|swift|c\+\+)\b", re.I), 4),  # "API in Go"-style
    (re.compile(r"(->|=>|::|lambda|#\!\/)"), 2),
]

REASONING_RULES = [
    (re.compile(r"\b(explain why|reason|analyze|analyse|evaluate|assess)\b", re.I), 3),
    (re.compile(r"\b(pros and cons|trade.?offs?|compare|versus|vs\.?)\b", re.I), 3),
    (re.compile(r"\b(step by step|walk me through|break (it|this) down|think through)\b", re.I), 4),
    (re.compile(r"\b(plan|strategy|architecture|design|approach|decision)\b", re.I), 2),
    (re.compile(r"\b(summarize|summary|research|investigate|literature)\b", re.I), 2),
    (re.compile(r"\b(why (does|is|should|would|did)|what (causes|happens|should))\b", re.I), 2),
    (re.compile(r"\b(math|equation|proof|calculate|formula|theorem|derive)\b", re.I), 3),
    (re.compile(r"\b(essay|argument|thesis|critique|opinion|perspective)\b", re.I), 2),
]

VISION_RULES = [
    (re.compile(r"\b(image|picture|photo|screenshot|diagram|chart|graph|figure)\b", re.I), 4),
    (re.compile(r"\b(describe|what is in|what does|look at|see|ocr|read)\s+(this|the|an?)?\s*(image|picture|photo|screenshot|diagram)\b", re.I), 5),
    (re.compile(r"\b(visual|pixel|color|colour|render|drawing|sketch)\b", re.I), 2),
    (re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|bmp)\b", re.I), 5),
]

# Negative signals: these REDUCE a category's score
CODE_NEGATIVES = re.compile(
    r"\b(explain|what is|define|meaning of|history of|philosophy)\b", re.I
)
REASONING_NEGATIVES = re.compile(
    r"\b(write the code|give me the code|show me code)\b", re.I
)

# ── Structural detectors ──────────────────────────────────────
STRUCT_CODE = re.compile(
    r"(```[\w]*\n|^\s{4}.+$|import \w+|def \w+\(|class \w+[:(]|"
    r"\$\s+\w+|\w+\.(py|js|ts|rs|go|cpp|java|sh))",
    re.MULTILINE
)
STRUCT_STACK_TRACE = re.compile(
    r"(Traceback|Error:|Exception:|at \w+\.\w+\(|File \".*\", line \d+)",
    re.MULTILINE
)
STRUCT_VISION = re.compile(
    r"(\[image\]|\[photo\]|<img|data:image/)",
    re.IGNORECASE
)


class TaskClassifier:

    def classify(self, prompt: str) -> TaskType:
        return self.classify_full(prompt).task_type

    def classify_full(self, prompt: str) -> ClassificationResult:
        """Full classification with confidence + debug signals."""
        p = prompt.strip()
        signals = []

        # ── 1. Hard structural signals ─────────────────────
        if STRUCT_VISION.search(p):
            signals.append("structural:image_tag")
            return ClassificationResult("vision", 1.0, {}, signals)

        if STRUCT_STACK_TRACE.search(p):
            signals.append("structural:stack_trace")
            return ClassificationResult("code", 0.95, {"code": 10}, signals)

        code_fences = p.count("```")
        if code_fences >= 2:
            signals.append(f"structural:code_fence×{code_fences//2}")
            return ClassificationResult("code", 0.92, {"code": 8}, signals)

        if STRUCT_CODE.search(p):
            signals.append("structural:code_syntax")

        # ── 2. Keyword scoring ────────────────────────────
        scores: dict[str, float] = {"code": 0.0, "reasoning": 0.0, "vision": 0.0}

        for pattern, weight in CODE_RULES:
            hits = len(pattern.findall(p))
            if hits:
                scores["code"] += hits * weight
                signals.append(f"code:{pattern.pattern[:30]}×{hits}")

        for pattern, weight in REASONING_RULES:
            hits = len(pattern.findall(p))
            if hits:
                scores["reasoning"] += hits * weight
                signals.append(f"reasoning:{pattern.pattern[:30]}×{hits}")

        for pattern, weight in VISION_RULES:
            hits = len(pattern.findall(p))
            if hits:
                scores["vision"] += hits * weight
                signals.append(f"vision:{pattern.pattern[:30]}×{hits}")

        # Apply negative signals
        if CODE_NEGATIVES.search(p):
            scores["code"] = max(0, scores["code"] - 2)
            signals.append("neg:code_explain_penalty")

        if REASONING_NEGATIVES.search(p):
            scores["reasoning"] = max(0, scores["reasoning"] - 3)
            signals.append("neg:reasoning_write_penalty")

        # Structural code syntax bonus (from step 1)
        if "structural:code_syntax" in signals:
            scores["code"] += 3

        # ── 3. Prompt-length heuristic ────────────────────
        # Short prompts (< 60 chars) without strong signals → general
        if len(p) < 60 and max(scores.values()) < 3:
            return ClassificationResult("general", 0.6, scores, signals + ["heuristic:short_prompt"])

        # ── 4. Pick winner ────────────────────────────────
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        if best_score == 0:
            return ClassificationResult("general", 0.5, scores, signals + ["fallback:no_signal"])

        # Tie: code+reasoning → prefer code for short prompts, reasoning for long
        if scores["code"] > 0 and scores["reasoning"] > 0:
            gap = abs(scores["code"] - scores["reasoning"])
            if gap < 2:
                best_type = "code" if len(p) < 300 else "reasoning"
                signals.append(f"tie_break:length={'code' if len(p)<300 else 'reasoning'}")

        # ── 5. Confidence ─────────────────────────────────
        total = sum(scores.values()) or 1
        confidence = min(0.98, best_score / total + 0.3)

        return ClassificationResult(best_type, round(confidence, 2), scores, signals)


# Singleton
task_classifier = TaskClassifier()

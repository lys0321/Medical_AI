"""Course content lives in data/courses/anatomy.json and is validated at import time.

Author-written teaching examples. All goals and rubrics require teacher review.
No textbook pages are asserted here. Questions use structured point-level answers
so offline grading does not mistake a keyword or a negated sentence for knowledge.
"""
from pathlib import Path

from course_loader import load_course_package

_PACKAGE = load_course_package(Path(__file__).resolve().parent / "data" / "courses" / "anatomy.json")
CONCEPTS = _PACKAGE["concepts"]
CONCEPT_MAP = _PACKAGE["concept_map"]
QUESTION_MAP = _PACKAGE["question_map"]
COURSE = _PACKAGE["course"]
SOURCES = _PACKAGE["sources"]
HINTS = _PACKAGE["hints"]

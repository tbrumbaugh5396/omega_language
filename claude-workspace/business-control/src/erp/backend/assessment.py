"""Quizzes and tests — the PURE grading core. Ported whole from lingua-portal.

Nothing here touches a database or a clock: grading takes the questions and the
responses and returns a result. That is what makes the rules that actually matter — partial credit,
what counts as answered, when a score is final — testable exhaustively and impossible to drift.

Four question kinds, and the split between them is the design:

    choice   one correct option        → graded AUTOMATICALLY
    multi    several correct options   → graded automatically, with partial credit
    text     a short written answer    → automatic only if the teacher supplied accepted answers
    speaking / video  a RECORDING      → graded by a human, always

The distinction that keeps the model honest is **auto-gradable vs human-graded**. A spoken answer
cannot be machine-marked here, and pretending otherwise would silently give students a score no one
stands behind. So an attempt containing recorded answers is *submitted* but not *final*: it carries
a provisional auto-score and stays in the teacher's grading queue until a human rules. `is_final`
tells you which, and the UI never shows a provisional score as though it were settled.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

CHOICE = "choice"
MULTI = "multi"
TEXT = "text"
SPEAKING = "speaking"
VIDEO = "video"
KINDS = (CHOICE, MULTI, TEXT, SPEAKING, VIDEO)

AUTO_KINDS = (CHOICE, MULTI, TEXT)      # text only when accepted answers are provided
RECORDED_KINDS = (SPEAKING, VIDEO)

STATE_OPEN = "open"
STATE_SUBMITTED = "submitted"
STATE_GRADED = "graded"


class QuizError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Question:
    id: int
    kind: str
    prompt: str
    choices: list[str] = field(default_factory=list)
    answer: list[int] = field(default_factory=list)      # indices into `choices`
    accepted: list[str] = field(default_factory=list)    # for TEXT
    points: int = 1
    position: int = 0

    @property
    def auto(self) -> bool:
        """Whether this question can be marked without a human."""
        if self.kind in (CHOICE, MULTI):
            return bool(self.answer)
        if self.kind == TEXT:
            return bool(self.accepted)
        return False


@dataclass(frozen=True)
class Response:
    question_id: int
    chosen: list[int] = field(default_factory=list)
    text: str = ""
    material_id: int | None = None       # the student's recording
    awarded: float | None = None         # a teacher's mark, when one exists
    feedback: str = ""


def normalise(s: str) -> str:
    """Compare written answers the way a teacher would: ignoring case, accents, and spacing.

    A Spanish learner typing "buenos dias" for "buenos días" has answered correctly; marking them
    wrong for a missing accent teaches them nothing about the language and everything about the
    software. Punctuation is dropped for the same reason.
    """
    s = unicodedata.normalize("NFKD", str(s or "").strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def grade_question(q: Question, r: Response | None) -> dict:
    """Mark one question. Returns points, whether it is settled, and why."""
    if r is None:
        return {"question_id": q.id, "points": 0.0, "max": float(q.points),
                "settled": True, "correct": False, "reason": "not answered"}

    # A human mark always wins, whatever the kind — a teacher may override an auto-grade.
    if r.awarded is not None:
        pts = max(0.0, min(float(q.points), float(r.awarded)))
        return {"question_id": q.id, "points": pts, "max": float(q.points),
                "settled": True, "correct": pts >= q.points, "reason": "graded by teacher"}

    if q.kind == CHOICE:
        ok = len(r.chosen) == 1 and r.chosen[0] in q.answer
        return {"question_id": q.id, "points": float(q.points) if ok else 0.0, "max": float(q.points),
                "settled": True, "correct": ok, "reason": "auto"}

    if q.kind == MULTI:
        # Partial credit, floored at zero: right options earn, wrong options cost the same. Marking
        # "select all" as all-or-nothing punishes a student who knew three of four; letting wrong
        # picks be free rewards selecting everything.
        want, got = set(q.answer), set(r.chosen)
        if not want:
            return {"question_id": q.id, "points": 0.0, "max": float(q.points), "settled": False,
                    "correct": False, "reason": "no answer key"}
        hit, miss = len(want & got), len(got - want)
        frac = max(0.0, (hit - miss) / len(want))
        pts = round(float(q.points) * frac, 2)
        return {"question_id": q.id, "points": pts, "max": float(q.points),
                "settled": True, "correct": frac >= 1.0, "reason": "auto (partial credit)"}

    if q.kind == TEXT:
        if not q.accepted:
            return {"question_id": q.id, "points": 0.0, "max": float(q.points), "settled": False,
                    "correct": False, "reason": "awaiting the teacher"}
        ok = normalise(r.text) in {normalise(a) for a in q.accepted}
        return {"question_id": q.id, "points": float(q.points) if ok else 0.0, "max": float(q.points),
                "settled": True, "correct": ok, "reason": "auto"}

    if q.kind in RECORDED_KINDS:
        if r.material_id is None:
            return {"question_id": q.id, "points": 0.0, "max": float(q.points), "settled": True,
                    "correct": False, "reason": "nothing recorded"}
        return {"question_id": q.id, "points": 0.0, "max": float(q.points), "settled": False,
                "correct": False, "reason": "awaiting the teacher"}

    raise QuizError("bad_kind", f"unknown question kind {q.kind!r}")


def grade_attempt(questions: list[Question], responses: list[Response], *, pass_mark: int = 60) -> dict:
    """Grade a whole attempt.

    `is_final` is the load-bearing field: it is False while ANY question still needs a human, and
    the score alongside it is explicitly provisional. Callers must not present a provisional score
    as a result.
    """
    by_q = {r.question_id: r for r in responses}
    marks = [grade_question(q, by_q.get(q.id)) for q in sorted(questions, key=lambda q: (q.position, q.id))]
    earned = sum(m["points"] for m in marks)
    total = sum(m["max"] for m in marks)
    pending = [m for m in marks if not m["settled"]]
    pct = round(100.0 * earned / total, 1) if total else 0.0
    return {
        "marks": marks,
        "earned": round(earned, 2),
        "total": round(total, 2),
        "percent": pct,
        "is_final": not pending,
        "pending": len(pending),
        # only meaningful once final; reported anyway so a caller cannot forget to check is_final
        "passed": bool(pct >= pass_mark) if not pending else None,
        "pass_mark": pass_mark,
    }


def validate_question(kind: str, prompt: str, choices: list[str], answer: list[int],
                      accepted: list[str], points: int) -> None:
    """Refuse questions that could never be answered or marked, at authoring time rather than
    silently at grading time."""
    if kind not in KINDS:
        raise QuizError("bad_kind", f"unknown question kind {kind!r}")
    if not str(prompt or "").strip():
        raise QuizError("no_prompt", "a question needs a prompt")
    if points < 1:
        raise QuizError("bad_points", "a question must be worth at least one point")
    if kind in (CHOICE, MULTI):
        if len(choices) < 2:
            raise QuizError("too_few_choices", "give at least two options")
        if not answer:
            raise QuizError("no_answer", "mark which option(s) are correct")
        if any(i < 0 or i >= len(choices) for i in answer):
            raise QuizError("bad_answer", "an answer refers to an option that does not exist")
        if kind == CHOICE and len(answer) != 1:
            raise QuizError("one_answer", "a single-choice question needs exactly one correct option")


def summarise_for_student(result: dict) -> dict:
    """What a student may see. A provisional score is NOT shown as a score — showing one is how a
    learner ends up believing they failed something no one has marked yet."""
    if not result["is_final"]:
        return {"is_final": False, "pending": result["pending"],
                "message": f"{result['pending']} answer(s) awaiting your teacher"}
    return {"is_final": True, "percent": result["percent"], "earned": result["earned"],
            "total": result["total"], "passed": result["passed"], "pass_mark": result["pass_mark"]}

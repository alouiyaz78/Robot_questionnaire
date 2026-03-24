from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import streamlit as st


SUPPORTED_UPLOAD_EXTS = [".pdf", ".txt", ".docx", ".py", ".ipynb"]


def ensure_src_on_path() -> None:
    import sys
    project_root = Path(__file__).resolve().parents[1]
    src_path = project_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


def save_uploaded_files(uploaded_files: List[Any]) -> List[str]:
    """
    Sauvegarde les fichiers uploadés dans un dossier temporaire
    et retourne la liste des chemins.
    """
    saved_paths: List[str] = []
    if not uploaded_files:
        return saved_paths

    temp_dir = Path(tempfile.mkdtemp(prefix="robot_qcm_"))

    for uploaded in uploaded_files:
        filename = uploaded.name
        suffix = Path(filename).suffix.lower()

        if suffix not in SUPPORTED_UPLOAD_EXTS:
            continue

        file_path = temp_dir / filename
        with open(file_path, "wb") as f:
            f.write(uploaded.getbuffer())

        saved_paths.append(str(file_path))

    return saved_paths


def save_single_uploaded_file(uploaded_file: Any) -> str | None:
    if uploaded_file is None:
        return None

    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_EXTS:
        return None

    temp_dir = Path(tempfile.mkdtemp(prefix="robot_qcm_consignes_"))
    file_path = temp_dir / uploaded_file.name
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str(file_path)


def init_session_state() -> None:
        defaults = {
        "api_key": "",
        "questions": [],
        "consignes_final": "",
        "quiz_generated": False,
        "submitted": False,
        "score_gained": 0.0,
        "score_total": 0.0,
        "user_answers": {},
        "run_dir": "",
        "difficulty": "moyen", }
        for k, v in defaults.items():
            if k not in st.session_state:
               st.session_state[k] = v


def render_question_input(question: Dict[str, Any], q_index: int) -> Any:
    qtype = question.get("type")
    key_base = f"q_{q_index}"

    st.markdown(f"### Question {q_index + 1} ({question.get('points', 2)} points)")
    st.write(question["text"])

    if qtype == "true_false":
        return st.radio(
            "Choix",
            options=["Vrai", "Faux"],
            key=key_base,
            index=None,
        )

    if qtype == "mcq_single":
        return st.radio(
            "Choix",
            options=question.get("options", []),
            key=key_base,
            index=None,
        )

    if qtype == "multi_select":
        return st.multiselect(
            "Choix multiples",
            options=question.get("options", []),
            key=key_base,
        )

    if qtype == "matching":
        answers = {}
        right_choices = question.get("right", [])
        st.write("Associez chaque élément :")
        for i, left_item in enumerate(question.get("left", []), start=1):
            selected = st.selectbox(
                f"{i}. {left_item}",
                options=["-- sélectionner --"] + right_choices,
                key=f"{key_base}_match_{i}",
            )
            if selected != "-- sélectionner --":
                answers[left_item] = selected
        return answers

    return None


def score_question(question: Dict[str, Any], user_answer: Any) -> Tuple[float, float]:
    pts = float(question.get("points", 2))
    ans = question.get("answer")
    qtype = question.get("type")

    if qtype in ("true_false", "mcq_single"):
        if user_answer is None:
            return (0.0, pts)
        return (pts, pts) if str(user_answer).strip() == str(ans).strip() else (0.0, pts)

    if qtype == "multi_select":
        if not (isinstance(ans, list) and isinstance(user_answer, list)):
            return (0.0, pts)

        correct_set = set(str(x).strip() for x in ans)
        user_set = set(str(x).strip() for x in user_answer)

        if not correct_set:
            return (0.0, pts)

        step = pts / len(correct_set)
        good = len(user_set & correct_set)
        bad = len(user_set - correct_set)

        score = (good * step) - (bad * step)
        score = max(0.0, min(pts, score))
        return (score, pts)

    if qtype == "matching":
        if not (isinstance(ans, dict) and isinstance(user_answer, dict)):
            return (0.0, pts)

        if not ans:
            return (0.0, pts)

        step = pts / len(ans)
        good = 0
        for left_item, correct_right in ans.items():
            if user_answer.get(left_item) == correct_right:
                good += 1

        score = good * step
        score = max(0.0, min(pts, score))
        return (score, pts)

    return (0.0, pts)


def compute_total_score(questions: List[Dict[str, Any]], user_answers: Dict[int, Any]) -> Tuple[float, float, List[Dict[str, Any]]]:
    gained = 0.0
    total = 0.0
    details: List[Dict[str, Any]] = []

    for i, q in enumerate(questions):
        ua = user_answers.get(i)
        sc, mx = score_question(q, ua)
        gained += sc
        total += mx
        details.append({
            "index": i + 1,
            "question": q.get("text", ""),
            "user_answer": ua,
            "correct_answer": q.get("answer"),
            "score": sc,
            "max_score": mx,
        })

    return gained, total, details


def format_percent(gained: float, total: float) -> float:
    if total == 0:
        return 0.0
    return round((gained / total) * 100, 2)
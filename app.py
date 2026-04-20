from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

import gradio as gr


# ------------------------------------------------------------
# Path setup
# ------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from robot_questionnaire.loaders import read_file
from robot_questionnaire.chunker import chunk_text, normalize_text
from robot_questionnaire.qcm import (
    build_client,
    normalize_instructions,
    generate_exam_questions_for_chunk,
    build_final_exam,
)
from robot_questionnaire.exam_formatter import (
    to_exam_markdown,
    to_answer_markdown,
    export_exam_docx,
)
from robot_questionnaire.io_utils import make_run_dir, write_text, write_json


SUPPORTED_EXTS = {".pdf", ".txt", ".docx", ".py", ".ipynb"}


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def format_percent(gained: float, total: float) -> float:
    if total == 0:
        return 0.0
    return round((gained / total) * 100, 2)


def pretty_answer(answer: Any) -> str:
    if answer is None:
        return "Aucune réponse"

    if isinstance(answer, list):
        return ", ".join(str(x) for x in answer) if answer else "Aucune réponse"

    if isinstance(answer, dict):
        if not answer:
            return "Aucune réponse"
        return "\n".join(f"- {k} → {v}" for k, v in answer.items())

    return str(answer)


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


def compute_total_score(
    questions: List[Dict[str, Any]],
    user_answers: Dict[int, Any],
) -> Tuple[float, float, List[Dict[str, Any]]]:
    gained = 0.0
    total = 0.0
    details: List[Dict[str, Any]] = []

    for i, q in enumerate(questions):
        ua = user_answers.get(i)
        sc, mx = score_question(q, ua)
        gained += sc
        total += mx
        details.append(
            {
                "index": i + 1,
                "question": q.get("text", ""),
                "question_type": q.get("type", ""),
                "user_answer": ua,
                "correct_answer": q.get("answer"),
                "score": sc,
                "max_score": mx,
            }
        )

    return gained, total, details


def build_result_markdown(
    questions: List[Dict[str, Any]],
    details: List[Dict[str, Any]],
    gained: float,
    total: float,
    pass_rate: float,
    deadline_ts: float,
) -> str:
    percent = format_percent(gained, total)
    passed = percent >= pass_rate * 100
    expired = deadline_ts > 0 and time.time() > deadline_ts

    lines: List[str] = []
    lines.append("## Résultat")
    lines.append(f"- **Score** : {gained:.2f}/{total:.2f}")
    lines.append(f"- **Pourcentage** : {percent}%")
    lines.append(f"- **Statut** : {'Réussi' if passed else 'Échec'}")

    if expired:
        lines.append("- **Temps** : Temps écoulé au moment de la correction")

    wrong_items = [d for d in details if d["score"] < d["max_score"]]

    if not wrong_items:
        lines.append("\n### Correction")
        lines.append("Toutes les réponses sont correctes.")
        return "\n".join(lines)

    lines.append("\n### Correction des réponses fausses")
    for d in wrong_items:
        q = questions[d["index"] - 1]
        lines.append(f"\n**Question {d['index']}**")
        lines.append(q.get("text", ""))
        lines.append(f"- **Ta réponse** : {pretty_answer(d['user_answer'])}")
        lines.append(f"- **Bonne réponse** : {pretty_answer(d['correct_answer'])}")

        qtype = q.get("type")
        if qtype == "multi_select":
            lines.append("- **Note** : question à réponses multiples, score partiel possible.")
        elif qtype == "matching":
            lines.append("- **Note** : question d'association, score partiel possible.")

    return "\n".join(lines)


def build_timer_html(duration_minutes: int) -> str:
    if duration_minutes <= 0:
        return "<div style='padding:8px 0;font-weight:600;'>Sans limite de temps</div>"

    total_seconds = duration_minutes * 60
    element_id = f"timer_{uuid.uuid4().hex}"

    return f"""
    <div id="{element_id}" style="padding:8px 0;font-weight:700;font-size:18px;">
      Temps restant: --:--
    </div>
    <script>
      (function() {{
        const total = {total_seconds};
        const el = document.getElementById("{element_id}");
        const start = Date.now();

        function update() {{
          const elapsed = Math.floor((Date.now() - start) / 1000);
          let remaining = Math.max(0, total - elapsed);
          const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
          const ss = String(remaining % 60).padStart(2, "0");
          el.textContent = "Temps restant: " + mm + ":" + ss;

          if (remaining <= 0) {{
            el.textContent = "Temps écoulé";
          }}
        }}

        update();
        const intervalId = setInterval(() => {{
          update();
          if (el.textContent === "Temps écoulé") {{
            clearInterval(intervalId);
          }}
        }}, 1000);
      }})();
    </script>
    """


def validate_uploaded_paths(paths: List[str] | None) -> List[str]:
    if not paths:
        return []

    valid = []
    for p in paths:
        suffix = Path(p).suffix.lower()
        if suffix in SUPPORTED_EXTS:
            valid.append(p)
    return valid


# ------------------------------------------------------------
# Quiz generation
# ------------------------------------------------------------
def generate_quiz(
    api_key: str,
    uploaded_docs: List[str] | None,
    consignes_file: str | None,
    nb_questions: int,
    lang: str,
    difficulty: str,
    pass_rate_percent: int,
    duration_minutes: int,
    normalize_rules: bool,
    export_md: bool,
    export_docx: bool,
):
    if not api_key.strip():
        raise gr.Error("Ajoute d'abord une clé API OpenAI.")

    doc_paths = validate_uploaded_paths(uploaded_docs)
    if not doc_paths:
        raise gr.Error("Importe au moins un document valide.")

    os.environ["OPENAI_API_KEY"] = api_key.strip()

    texts = []
    errors = []

    for path in doc_paths:
        try:
            txt = read_file(path)
            if txt and txt.strip():
                texts.append(f"\n\n===== SOURCE: {path} =====\n\n{txt}")
            else:
                errors.append({"file": path, "error": "Texte vide"})
        except Exception as e:
            errors.append({"file": path, "error": str(e)})

    full_text = normalize_text("\n".join(texts))
    if not full_text.strip():
        raise gr.Error("Aucun texte exploitable après extraction.")

    client = build_client()

    consignes_final = ""
    if consignes_file:
        raw_consignes = read_file(consignes_file)
        if raw_consignes.strip():
            consignes_final = (
                normalize_instructions(client, raw_consignes, lang=lang)
                if normalize_rules
                else raw_consignes
            )

    chunks = chunk_text(full_text, max_chars=6000, overlap=400)

    per_chunk = max(1, int(nb_questions) // max(1, len(chunks)))
    leftover = int(nb_questions) - per_chunk * len(chunks)

    blocks = []
    for idx, chunk in enumerate(chunks):
        n = per_chunk + (1 if idx < leftover else 0)
        block = generate_exam_questions_for_chunk(
            client=client,
            chunk=chunk,
            n=n,
            lang=lang,
            instructions=consignes_final,
            difficulty=difficulty,
        )
        blocks.append(block)

    questions = build_final_exam(blocks, target_n=int(nb_questions), seed=42)
    if not questions:
        raise gr.Error("Aucune question générée.")

    run_dir = make_run_dir("outputs")
    write_json(f"{run_dir}/sources.json", {"errors": errors, "files_count": len(doc_paths)})
    write_text(f"{run_dir}/extracted.txt", full_text)
    write_text(f"{run_dir}/consignes.txt", consignes_final)
    write_json(
        f"{run_dir}/exam.json",
        {
            "questions": questions,
            "difficulty": difficulty,
            "pass_rate_percent": pass_rate_percent,
            "duration_minutes": duration_minutes,
        },
    )

    exam_md_path = None
    corr_md_path = None
    exam_docx_path = None
    corr_docx_path = None

    if export_md:
        exam_md_path = f"{run_dir}/qcm_exam.md"
        corr_md_path = f"{run_dir}/corrige_exam.md"
        write_text(exam_md_path, to_exam_markdown(questions))
        write_text(corr_md_path, to_answer_markdown(questions))

    if export_docx:
        exam_docx_path = f"{run_dir}/questionnaire.docx"
        corr_docx_path = f"{run_dir}/corrige.docx"
        export_exam_docx(
            filepath=exam_docx_path,
            title=f"Questionnaire ({difficulty})",
            questions=questions,
            include_answers=False,
            user_answers=None,
        )
        export_exam_docx(
            filepath=corr_docx_path,
            title=f"Questionnaire - Corrigé ({difficulty})",
            questions=questions,
            include_answers=True,
            user_answers=None,
        )

    deadline_ts = time.time() + duration_minutes * 60 if duration_minutes > 0 else 0.0

    quiz_state = {
        "questions": questions,
        "run_dir": run_dir,
        "difficulty": difficulty,
        "pass_rate": pass_rate_percent / 100.0,
        "consignes_final": consignes_final,
        "deadline_ts": deadline_ts,
    }

    status_md = f"""
## Questionnaire généré
- **Questions** : {len(questions)}
- **Niveau** : {difficulty}
- **Langue** : {lang}
- **Seuil de réussite** : {pass_rate_percent}%
- **Temps** : {"Sans limite" if duration_minutes <= 0 else f"{duration_minutes} minute(s)"}
- **Dossier de sortie** : `{run_dir}`
"""

    timer_html = build_timer_html(duration_minutes)

    return (
        quiz_state,
        None,
        status_md,
        timer_html,
        gr.update(value=exam_md_path, visible=bool(exam_md_path)),
        gr.update(value=corr_md_path, visible=bool(corr_md_path)),
        gr.update(value=exam_docx_path, visible=bool(exam_docx_path)),
        gr.update(value=corr_docx_path, visible=bool(corr_docx_path)),
    )


# ------------------------------------------------------------
# Gradio UI
# ------------------------------------------------------------
with gr.Blocks(title="Robot Questionnaire - Gradio") as demo:
    quiz_state = gr.State({})
    result_state = gr.State(None)

    gr.Markdown("# Robot Questionnaire")
    gr.Markdown(
        "Génération de QCM à partir de documents, passage du questionnaire, score et correction des erreurs."
    )

    with gr.Row():
        with gr.Column(scale=1):
            api_key = gr.Textbox(label="Clé API OpenAI", type="password")
            uploaded_docs = gr.File(
                label="Documents du cours",
                file_count="multiple",
                file_types=[".pdf", ".txt", ".docx", ".py", ".ipynb"],
                type="filepath",
            )
            consignes_file = gr.File(
                label="Fichier de consignes (optionnel)",
                file_count="single",
                file_types=[".pdf", ".txt", ".docx", ".py", ".ipynb"],
                type="filepath",
            )

            nb_questions = gr.Slider(5, 50, value=20, step=1, label="Nombre de questions")
            lang = gr.Dropdown(["fr", "en"], value="fr", label="Langue")
            difficulty = gr.Dropdown(
                ["facile", "moyen", "difficile"],
                value="moyen",
                label="Niveau de difficulté",
            )
            pass_rate_percent = gr.Slider(0, 100, value=60, step=5, label="Seuil de réussite (%)")
            duration_minutes = gr.Number(value=20, precision=0, label="Temps (minutes, 0 = illimité)")
            normalize_rules = gr.Checkbox(value=True, label="Normaliser les consignes automatiquement")
            export_md = gr.Checkbox(value=True, label="Exporter Markdown")
            export_docx = gr.Checkbox(value=True, label="Exporter Word (.docx)")

            generate_btn = gr.Button("Générer le questionnaire", variant="primary")

        with gr.Column(scale=1):
            status_md = gr.Markdown()
            timer_html = gr.HTML()
            exam_md_file = gr.File(label="Questionnaire (.md)", visible=False)
            corr_md_file = gr.File(label="Corrigé (.md)", visible=False)
            exam_docx_file = gr.File(label="Questionnaire (.docx)", visible=False)
            corr_docx_file = gr.File(label="Corrigé (.docx)", visible=False)

    generate_btn.click(
        fn=generate_quiz,
        inputs=[
            api_key,
            uploaded_docs,
            consignes_file,
            nb_questions,
            lang,
            difficulty,
            pass_rate_percent,
            duration_minutes,
            normalize_rules,
            export_md,
            export_docx,
        ],
        outputs=[
            quiz_state,
            result_state,
            status_md,
            timer_html,
            exam_md_file,
            corr_md_file,
            exam_docx_file,
            corr_docx_file,
        ],
    )

    @gr.render(inputs=[quiz_state, result_state])
    def render_quiz(quiz_data, current_result):
        questions = quiz_data.get("questions", []) if isinstance(quiz_data, dict) else []
        if not questions:
            gr.Markdown("Le questionnaire apparaîtra ici après génération.")
            return

        consignes_final = quiz_data.get("consignes_final", "")
        deadline_ts = float(quiz_data.get("deadline_ts", 0.0))
        pass_rate = float(quiz_data.get("pass_rate", 0.6))
        run_dir = quiz_data.get("run_dir", "outputs")

        if consignes_final:
            with gr.Accordion("Consignes appliquées", open=False):
                gr.Markdown(consignes_final)

        answer_components: List[Any] = []
        answer_specs: List[Dict[str, Any]] = []

        gr.Markdown("## Questionnaire")

        for idx, question in enumerate(questions):
            qtype = question.get("type")
            pts = question.get("points", 2)

            with gr.Group():
                gr.Markdown(f"### Question {idx + 1} ({pts} points)")
                gr.Markdown(question.get("text", ""))

                if qtype == "true_false":
                    comp = gr.Radio(["Vrai", "Faux"], label="Choix")
                    answer_components.append(comp)
                    answer_specs.append({"type": "single", "q_index": idx})

                elif qtype == "mcq_single":
                    comp = gr.Radio(question.get("options", []), label="Choix")
                    answer_components.append(comp)
                    answer_specs.append({"type": "single", "q_index": idx})

                elif qtype == "multi_select":
                    comp = gr.CheckboxGroup(question.get("options", []), label="Choix multiples")
                    answer_components.append(comp)
                    answer_specs.append({"type": "multi", "q_index": idx})

                elif qtype == "matching":
                    gr.Markdown("Associez chaque élément :")
                    for left_item in question.get("left", []):
                        comp = gr.Dropdown(
                            question.get("right", []),
                            label=left_item,
                            multiselect=False,
                        )
                        answer_components.append(comp)
                        answer_specs.append(
                            {
                                "type": "matching_item",
                                "q_index": idx,
                                "left_item": left_item,
                            }
                        )

                else:
                    gr.Markdown("Type de question non supporté.")

        submit_btn = gr.Button("Corriger mes réponses", variant="primary")
        result_md = gr.Markdown(value=current_result["summary"] if current_result else "")
        user_docx_file = gr.File(
            label="Questionnaire avec réponses utilisateur (.docx)",
            value=current_result["user_docx"] if current_result else None,
            visible=bool(current_result and current_result.get("user_docx")),
        )

        def submit_answers(*vals):
            raw_values = vals[:-1]
            quiz_data_local = vals[-1]
            questions_local = quiz_data_local["questions"]
            run_dir_local = quiz_data_local["run_dir"]
            pass_rate_local = float(quiz_data_local["pass_rate"])
            deadline_ts_local = float(quiz_data_local.get("deadline_ts", 0.0))
            difficulty_local = quiz_data_local.get("difficulty", "moyen")

            user_answers: Dict[int, Any] = {}

            for spec, raw in zip(answer_specs, raw_values):
                q_index = spec["q_index"]

                if spec["type"] == "single":
                    user_answers[q_index] = raw

                elif spec["type"] == "multi":
                    user_answers[q_index] = raw or []

                elif spec["type"] == "matching_item":
                    if q_index not in user_answers or not isinstance(user_answers[q_index], dict):
                        user_answers[q_index] = {}
                    if raw:
                        user_answers[q_index][spec["left_item"]] = raw

            gained, total, details = compute_total_score(questions_local, user_answers)
            summary = build_result_markdown(
                questions_local,
                details,
                gained,
                total,
                pass_rate_local,
                deadline_ts_local,
            )

            write_json(f"{run_dir_local}/user_answers.json", details)

            user_docx_path = f"{run_dir_local}/questionnaire_avec_reponses.docx"
            export_exam_docx(
                filepath=user_docx_path,
                title=f"Questionnaire - Réponses utilisateur ({difficulty_local})",
                questions=questions_local,
                include_answers=True,
                user_answers=[
                    {"user_answer": user_answers.get(idx)}
                    for idx in range(len(questions_local))
                ],
            )

            result_payload = {
                "summary": summary,
                "user_docx": user_docx_path,
            }

            return (
                result_payload,
                summary,
                gr.update(value=user_docx_path, visible=True),
            )

        submit_btn.click(
            fn=submit_answers,
            inputs=answer_components + [quiz_state],
            outputs=[result_state, result_md, user_docx_file],
        )

demo.launch()
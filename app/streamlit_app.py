from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from utils_ui import (
    ensure_src_on_path,
    save_uploaded_files,
    save_single_uploaded_file,
    init_session_state,
    render_question_input,
    compute_total_score,
    format_percent,
)

ensure_src_on_path()

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


st.set_page_config(page_title="Robot Questionnaire", page_icon="🧠", layout="wide")
init_session_state()

st.title("🧠 Robot Questionnaire")
st.caption("Génération de quiz à partir de documents avec scoring automatique.")

with st.sidebar:
    st.header("Configuration")

    api_key = st.text_input(
        "Clé API OpenAI",
        type="password",
        value=st.session_state["api_key"],
        help="La clé reste dans la session actuelle. Elle n'est pas affichée."
    )
    st.session_state["api_key"] = api_key

    nb_questions = st.number_input("Nombre de questions", min_value=5, max_value=100, value=20, step=1)
    lang = st.selectbox("Langue", ["fr", "en"], index=0)

    difficulty = st.selectbox(
        "Niveau de difficulté",
        ["facile", "moyen", "difficile"],
        index=1,
        help="Facile = compréhension directe, Moyen = application/comparaison simple, Difficile = interprétation/comparaison avancée"
    )

    pass_rate_percent = st.slider("Seuil de réussite (%)", min_value=0, max_value=100, value=60, step=5)
    pass_rate = pass_rate_percent / 100.0

    st.markdown("---")
    uploaded_docs = st.file_uploader(
        "Importer les documents du cours",
        type=["pdf", "txt", "docx", "py", "ipynb"],
        accept_multiple_files=True,
    )

    uploaded_consignes = st.file_uploader(
        "Importer un fichier de consignes (optionnel)",
        type=["pdf", "txt", "docx", "py", "ipynb"],
        accept_multiple_files=False,
    )

    normalize_rules = st.checkbox("Normaliser les consignes automatiquement", value=True)
    export_md = st.checkbox("Exporter Markdown", value=True)
    export_docx = st.checkbox("Exporter Word (.docx)", value=True)

    generate_btn = st.button("🚀 Générer le questionnaire", use_container_width=True)

if generate_btn:
    if not st.session_state["api_key"].strip():
        st.error("Ajoute d'abord une clé API OpenAI.")
        st.stop()

    if not uploaded_docs:
        st.error("Importe au moins un document.")
        st.stop()

    os.environ["OPENAI_API_KEY"] = st.session_state["api_key"]

    with st.spinner("Lecture des documents..."):
        doc_paths = save_uploaded_files(uploaded_docs)
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
            st.error("Aucun texte exploitable après extraction.")
            st.stop()

    with st.spinner("Préparation du modèle..."):
        client = build_client()

        consignes_final = ""
        if uploaded_consignes is not None:
            consignes_path = save_single_uploaded_file(uploaded_consignes)
            raw_consignes = read_file(consignes_path) if consignes_path else ""
            if raw_consignes.strip():
                consignes_final = normalize_instructions(client, raw_consignes, lang=lang) if normalize_rules else raw_consignes

        chunks = chunk_text(full_text, max_chars=6000, overlap=400)

    with st.spinner("Génération des questions..."):
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
            st.error("Aucune question générée.")
            st.stop()

    run_dir = make_run_dir("outputs")
    write_json(f"{run_dir}/sources.json", {"errors": errors, "files_count": len(doc_paths)})
    write_text(f"{run_dir}/extracted.txt", full_text)
    write_text(f"{run_dir}/consignes.txt", consignes_final)
    write_json(f"{run_dir}/exam.json", {"questions": questions, "difficulty": difficulty})

    if export_md:
        write_text(f"{run_dir}/qcm_exam.md", to_exam_markdown(questions))
        write_text(f"{run_dir}/corrige_exam.md", to_answer_markdown(questions))

    if export_docx:
        export_exam_docx(
            filepath=f"{run_dir}/questionnaire.docx",
            title=f"Questionnaire ({difficulty})",
            questions=questions,
            include_answers=False,
            user_answers=None,
        )
        export_exam_docx(
            filepath=f"{run_dir}/corrige.docx",
            title=f"Questionnaire - Corrigé ({difficulty})",
            questions=questions,
            include_answers=True,
            user_answers=None,
        )

    st.session_state["questions"] = questions
    st.session_state["consignes_final"] = consignes_final
    st.session_state["quiz_generated"] = True
    st.session_state["submitted"] = False
    st.session_state["user_answers"] = {}
    st.session_state["run_dir"] = run_dir
    st.session_state["difficulty"] = difficulty

    st.success("Questionnaire généré avec succès.")

if st.session_state["quiz_generated"]:
    st.subheader("Questionnaire")
    st.write(f"Niveau sélectionné : **{st.session_state.get('difficulty', 'moyen')}**")

    if st.session_state["consignes_final"]:
        with st.expander("Consignes appliquées"):
            st.write(st.session_state["consignes_final"])

    user_answers = {}

    for i, question in enumerate(st.session_state["questions"]):
        with st.container(border=True):
            answer = render_question_input(question, i)
            user_answers[i] = answer

    if st.button("✅ Soumettre mes réponses", use_container_width=True):
        gained, total, details = compute_total_score(st.session_state["questions"], user_answers)
        percent = format_percent(gained, total)

        st.session_state["submitted"] = True
        st.session_state["score_gained"] = gained
        st.session_state["score_total"] = total
        st.session_state["user_answers"] = user_answers

        write_json(f"{st.session_state['run_dir']}/user_answers.json", details)

        if Path(st.session_state["run_dir"]).exists():
            try:
                export_exam_docx(
                    filepath=f"{st.session_state['run_dir']}/questionnaire_avec_reponses.docx",
                    title=f"Questionnaire - Réponses utilisateur ({st.session_state.get('difficulty', 'moyen')})",
                    questions=st.session_state["questions"],
                    include_answers=True,
                    user_answers=[
                        {"user_answer": user_answers.get(idx)}
                        for idx in range(len(st.session_state["questions"]))
                    ],
                )
            except Exception as e:
                st.warning(f"Export DOCX utilisateur impossible: {e}")

        st.rerun()

if st.session_state["submitted"]:
    gained = st.session_state["score_gained"]
    total = st.session_state["score_total"]
    percent = format_percent(gained, total)

    st.subheader("Résultat")
    c1, c2, c3 = st.columns(3)
    c1.metric("Score", f"{gained:.2f}/{total:.2f}")
    c2.metric("Pourcentage", f"{percent}%")
    c3.metric("Statut", "Réussi" if percent >= pass_rate * 100 else "Échec")

    st.info(f"Dossier de sortie : {st.session_state['run_dir']}")

    exam_md_path = Path(st.session_state["run_dir"]) / "qcm_exam.md"
    corr_md_path = Path(st.session_state["run_dir"]) / "corrige_exam.md"
    exam_docx_path = Path(st.session_state["run_dir"]) / "questionnaire.docx"
    corr_docx_path = Path(st.session_state["run_dir"]) / "corrige.docx"

    st.markdown("### Téléchargements")

    col1, col2 = st.columns(2)

    with col1:
        if exam_md_path.exists():
            with open(exam_md_path, "rb") as f:
                st.download_button("Télécharger questionnaire (.md)", f, file_name="qcm_exam.md")
        if exam_docx_path.exists():
            with open(exam_docx_path, "rb") as f:
                st.download_button("Télécharger questionnaire (.docx)", f, file_name="questionnaire.docx")

    with col2:
        if corr_md_path.exists():
            with open(corr_md_path, "rb") as f:
                st.download_button("Télécharger corrigé (.md)", f, file_name="corrige_exam.md")
        if corr_docx_path.exists():
            with open(corr_docx_path, "rb") as f:
                st.download_button("Télécharger corrigé (.docx)", f, file_name="corrige.docx")
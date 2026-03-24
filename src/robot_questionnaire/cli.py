import argparse
import random
from typing import Any, Dict, List, Tuple

from robot_questionnaire.loaders import list_files, read_file
from robot_questionnaire.chunker import chunk_text, normalize_text
from robot_questionnaire.qcm import (
    build_client,
    normalize_instructions,
    generate_exam_questions_for_chunk,
    build_final_exam,
)
from robot_questionnaire.io_utils import make_run_dir, write_text, write_json
from robot_questionnaire.exam_formatter import (
    to_exam_markdown,
    to_answer_markdown,
    export_exam_docx,
)


def parse_args():
    p = argparse.ArgumentParser(prog="robot-qcm", description="Génère un QCM style examen + interactive + exports.")
    p.add_argument("-i", "--input", nargs="+", required=True, help="Fichiers/dossiers (ex: /mnt/e/.../cours)")
    p.add_argument("-n", "--n-questions", type=int, default=20)
    p.add_argument("--max-chars", type=int, default=6000)
    p.add_argument("--overlap", type=int, default=400)
    p.add_argument("--lang", choices=["fr", "en"], default="fr")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--outdir", default="outputs")

    # Consignes via fichier
    p.add_argument("--consignes", default=None, help="Fichier consignes (pdf/txt/docx)")
    p.add_argument("--no-normalize-consignes", action="store_true")

    # Mode console
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--pass-rate", type=float, default=0.60)

    # Exports
    p.add_argument("--export-docx", action="store_true", help="Option B: génère un Word .docx")
    p.add_argument("--export-md", action="store_true", help="Génère aussi les .md examen + corrigé")

    return p.parse_args()


def _norm_choice(s: str) -> str:
    return s.strip().lower()


def _ask_mcq_single(options: List[str]) -> str:
    for idx, opt in enumerate(options, start=1):
        print(f"  {idx}) {opt}")
    while True:
        ans = input("Votre choix (numéro) : ").strip()
        if ans.isdigit():
            k = int(ans)
            if 1 <= k <= len(options):
                return options[k - 1]
        print("⚠️ Réponse invalide. Entrez un numéro valide.")


def _ask_true_false() -> str:
    while True:
        ans = _norm_choice(input("Vrai ou Faux ? ").strip())
        if ans in ("vrai", "v", "true", "t"):
            return "Vrai"
        if ans in ("faux", "f", "false"):
            return "Faux"
        print("⚠️ Réponse invalide. Tape 'Vrai' ou 'Faux'.")


def _ask_multi_select(options: List[str]) -> List[str]:
    print("(Plusieurs réponses possibles. Exemple: 1,3,4)")
    for idx, opt in enumerate(options, start=1):
        print(f"  {idx}) {opt}")
    while True:
        raw = input("Vos choix : ").strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts:
            print("⚠️ Entrez au moins un numéro.")
            continue
        picks = []
        ok = True
        for p in parts:
            if not p.isdigit():
                ok = False
                break
            k = int(p)
            if not (1 <= k <= len(options)):
                ok = False
                break
            picks.append(options[k - 1])
        if ok:
            # dédoublonne
            out = []
            for x in picks:
                if x not in out:
                    out.append(x)
            return out
        print("⚠️ Format invalide. Exemple attendu: 1,3")


def _ask_matching(left: List[str], right: List[str]) -> Dict[str, str]:
    print("Colonne A (choix):")
    for idx, r in enumerate(right, start=1):
        print(f"  {idx}) {r}")
    print("\nColonne B (items à associer):")
    for idx, l in enumerate(left, start=1):
        print(f"  {idx}. {l}")

    mapping: Dict[str, str] = {}
    print("\nRépondez sous la forme: item_num=choice_num (ex: 1=2). Tapez 'done' pour finir.")
    while True:
        raw = input("> ").strip()
        if raw.lower() == "done":
            break
        if "=" not in raw:
            print("⚠️ Format invalide. Exemple: 1=2")
            continue
        a, b = raw.split("=", 1)
        a = a.strip()
        b = b.strip()
        if not (a.isdigit() and b.isdigit()):
            print("⚠️ Utilisez des numéros.")
            continue
        ai = int(a)
        bi = int(b)
        if not (1 <= ai <= len(left) and 1 <= bi <= len(right)):
            print("⚠️ Numéros hors plage.")
            continue
        mapping[left[ai - 1]] = right[bi - 1]

    return mapping


def _score_question(q: Dict[str, Any], user_answer: Any) -> Tuple[float, float]:
    pts = float(q.get("points", 2))
    ans = q.get("answer")
    qtype = q.get("type")

    # Open long : non noté automatiquement (0) — tu peux améliorer plus tard avec correction LLM
    if qtype == "open_long":
        return 0.0, pts

    if qtype in ("true_false", "mcq_single"):
        return (pts, pts) if str(user_answer).strip() == str(ans).strip() else (0.0, pts)

    if qtype == "multi_select":
        # ✅ Scoring partiel:
        # + (pts/nb_bonnes) pour chaque bonne réponse cochée
        # - (pts/nb_bonnes) pour chaque mauvaise réponse cochée
        # pas de pénalité pour les bonnes réponses oubliées
        # score borné [0, pts]
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
        if isinstance(ans, dict) and isinstance(user_answer, dict):
            return (pts, pts) if user_answer == ans else (0.0, pts)
        return (0.0, pts)

    return (0.0, pts)


def run_interactive_exam(questions: List[Dict[str, Any]], pass_rate: float) -> Tuple[float, float, List[Dict[str, Any]]]:
    print("\n==================== EXAMEN ====================\n")
    gained = 0.0
    total = 0.0
    user_log: List[Dict[str, Any]] = []

    for i, q in enumerate(questions, start=1):
        pts = float(q.get("points", 2))
        total += pts
        print(f"\nQuestion {i} ({int(pts)} points)")
        print(q["text"])

        qtype = q.get("type")
        ua = None

        if qtype == "true_false":
            ua = _ask_true_false()

        elif qtype == "mcq_single":
            ua = _ask_mcq_single(q.get("options", []))

        elif qtype == "multi_select":
            ua = _ask_multi_select(q.get("options", []))

        elif qtype == "matching":
            ua = _ask_matching(q.get("left", []), q.get("right", []))

        elif qtype == "open_long":
            print(q.get("instruction", "Répondez en 10–15 lignes."))
            ua = input("Votre réponse (résumé) : ").strip()

        else:
            print("⚠️ Type non supporté, saut.")
            ua = ""

        sc, max_sc = _score_question(q, ua)
        gained += sc

        user_log.append({"index": i, "user_answer": ua, "score": sc, "max": max_sc})

    rate = (gained / total) if total else 0.0
    print("\n================== RÉSULTAT ==================\n")
    print(f"Score: {gained:.1f}/{total:.1f} = {rate*100:.2f}%")
    print("✅ Réussi" if rate >= pass_rate else "❌ Échec", f"(seuil: {pass_rate*100:.0f}%)")

    return gained, total, user_log


def main():
    args = parse_args()
    random.seed(args.seed)

    files = list_files(args.input)
    if not files:
        print("⚠️ Aucun fichier supporté trouvé (pdf/txt/docx).")
        return

    print(f"✅ {len(files)} fichier(s) trouvé(s). Extraction...")
    texts: List[str] = []
    errors = []

    for f in files:
        try:
            t = read_file(f)
            if t and t.strip():
                texts.append(f"\n\n===== SOURCE: {f} =====\n\n{t}")
            else:
                errors.append({"file": f, "error": "Texte vide"})
        except Exception as e:
            errors.append({"file": f, "error": str(e)})

    full_text = normalize_text("\n".join(texts))
    if not full_text.strip():
        print("⚠️ Aucun texte exploitable après extraction.")
        return

    chunks = chunk_text(full_text, max_chars=args.max_chars, overlap=args.overlap)
    print(f"✅ Texte découpé en {len(chunks)} chunk(s).")

    client = build_client()

    # Consignes (facultatif)
    consignes_final = ""
    if args.consignes:
        raw = read_file(args.consignes)
        consignes_final = raw if args.no_normalize_consignes else normalize_instructions(client, raw, lang=args.lang)
        print("✅ Consignes chargées.")

    # Répartir questions
    per_chunk = max(1, args.n_questions // max(1, len(chunks)))
    leftover = args.n_questions - per_chunk * len(chunks)

    print("🤖 Génération des questions (format examen)...")
    blocks: List[List[Dict[str, Any]]] = []
    for idx, c in enumerate(chunks):
        n = per_chunk + (1 if idx < leftover else 0)
        blocks.append(generate_exam_questions_for_chunk(client, c, n=n, lang=args.lang, instructions=consignes_final))

    questions = build_final_exam(blocks, target_n=args.n_questions, seed=args.seed)

    run_dir = make_run_dir(args.outdir)
    write_json(f"{run_dir}/sources.json", {"files": files, "errors": errors})
    write_text(f"{run_dir}/extracted.txt", full_text)
    write_text(f"{run_dir}/consignes.txt", consignes_final)

    # Exports MD
    if args.export_md:
        exam_md = to_exam_markdown(questions)
        ans_md = to_answer_markdown(questions)
        write_text(f"{run_dir}/qcm_exam.md", exam_md)
        write_text(f"{run_dir}/corrige_exam.md", ans_md)

    # Interactive
    gained = 0.0
    total = 0.0
    user_log: List[Dict[str, Any]] = []
    if args.interactive:
        gained, total, user_log = run_interactive_exam(questions, pass_rate=args.pass_rate)
        write_json(f"{run_dir}/user_answers.json", user_log)

    # Export DOCX (Option B)
    if args.export_docx:
        title = "Questionnaire"
        export_exam_docx(
            filepath=f"{run_dir}/questionnaire.docx",
            title=title,
            questions=questions,
            include_answers=False,
            user_answers=user_log if user_log else None,
        )
        export_exam_docx(
            filepath=f"{run_dir}/corrige.docx",
            title=title + " - Corrigé",
            questions=questions,
            include_answers=True,
            user_answers=user_log if user_log else None,
        )
        print(f"📄 DOCX générés: {run_dir}/questionnaire.docx et {run_dir}/corrige.docx")

    # Save JSON exam
    write_json(f"{run_dir}/exam.json", {"questions": questions})

    print("\n✅ Terminé.")
    print(f"📁 Dossier: {run_dir}")


if __name__ == "__main__":
    main()

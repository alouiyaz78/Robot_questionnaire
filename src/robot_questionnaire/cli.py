import argparse
import random
from typing import List, Dict, Tuple

from robot_questionnaire.loaders import list_files, read_file
from robot_questionnaire.chunker import chunk_text, normalize_text
from robot_questionnaire.qcm import (
    build_client,
    normalize_instructions,
    generate_questions_for_chunk,
    generate_answer_key,
    build_final_qcm,
)
from robot_questionnaire.io_utils import make_run_dir, write_text, write_json


def parse_args():
    p = argparse.ArgumentParser(
        prog="robot-qcm",
        description="Génère un QCM + corrigé à partir de fichiers PDF/DOCX/TXT."
    )
    p.add_argument(
        "-i", "--input",
        nargs="+",
        required=True,
        help="Chemins de fichiers ou dossiers (WSL: ex /mnt/e/projet_1_securité/cours)"
    )
    p.add_argument("-n", "--n-questions", type=int, default=15, help="Nombre total de questions")
    p.add_argument("--max-chars", type=int, default=6000, help="Taille max d'un chunk (caractères)")
    p.add_argument("--overlap", type=int, default=400, help="Chevauchement entre chunks")
    p.add_argument("--lang", choices=["fr", "en"], default="fr", help="Langue du QCM")
    p.add_argument("--seed", type=int, default=42, help="Graine aléatoire")
    p.add_argument("--outdir", default="outputs", help="Dossier de sortie (par défaut: outputs)")

    # ✅ Consignes depuis un document
    p.add_argument("--consignes", help="Fichier (pdf/txt/docx) de consignes à appliquer", default=None)
    p.add_argument("--no-normalize-consignes", action="store_true", help="Ne pas résumer/normaliser les consignes")

    # ✅ Mode quiz
    p.add_argument("--interactive", action="store_true", help="Pose le QCM dans la console et calcule le score")
    p.add_argument("--pass-rate", type=float, default=0.60, help="Seuil de réussite (ex: 0.60 = 60%)")
    p.add_argument("--export-qa", action="store_true", help="Génère un rapport final Questions+Réponses+Tes réponses")

    return p.parse_args()


def parse_answer_key(corrige_text: str) -> Dict[int, str]:
    key = {}
    for line in corrige_text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        left, right = line.split(":", 1)
        try:
            qn = int(left.strip())
        except ValueError:
            continue
        ans = right.strip().capitalize()
        key[qn] = ans
    return key


def normalize_user_answer(s: str) -> str:
    s = s.strip().lower()
    mapping = {
        "a": "A", "b": "B", "c": "C", "d": "D",
        "vrai": "Vrai", "true": "Vrai", "v": "Vrai", "t": "Vrai",
        "faux": "Faux", "false": "Faux", "f": "Faux",
    }
    return mapping.get(s, s.capitalize())


def run_interactive(qcm_text: str, corrige_text: str, pass_rate: float) -> Tuple[float, List[Tuple[int, str, str]], Dict[int, str]]:
    key = parse_answer_key(corrige_text)
    if not key:
        print("⚠️ Corrigé illisible (format inattendu).")
        return 0.0, [], {}

    print("\n==================== QCM ====================\n")
    print(qcm_text)
    print("\n=============================================\n")

    user_answers: Dict[int, str] = {}
    errors: List[Tuple[int, str, str]] = []

    total = len(key)
    correct = 0

    for qn in sorted(key.keys()):
        raw = input(f"Réponse Q{qn} (A/B/C/D ou Vrai/Faux) : ")
        ua = normalize_user_answer(raw)
        user_answers[qn] = ua

        good = key[qn]
        if ua == good:
            correct += 1
        else:
            errors.append((qn, ua, good))

    score = correct / total if total else 0.0
    pct = round(score * 100, 2)
    threshold = round(pass_rate * 100, 2)

    print("\n================== RÉSULTAT ==================\n")
    print(f"Score: {correct}/{total} = {pct}%")
    print("✅ Réussi" if score >= pass_rate else "❌ Échec", f"(seuil: {threshold}%)")

    if errors:
        print("\nErreurs:")
        for qn, ua, good in errors:
            print(f" - Q{qn}: toi={ua} | correct={good}")

    return score, errors, user_answers


def build_qa_report_md(qcm_text: str, corrige_text: str, user_answers: Dict[int, str], score: float, pass_rate: float, consignes: str) -> str:
    key = parse_answer_key(corrige_text)
    pct = round(score * 100, 2)
    threshold = round(pass_rate * 100, 2)
    status = "RÉUSSI ✅" if score >= pass_rate else "ÉCHEC ❌"

    lines = ["| # | Ta réponse | Bonne réponse |", "|---:|:---------:|:------------:|"]
    for qn in sorted(key.keys()):
        ua = user_answers.get(qn, "")
        lines.append(f"| {qn} | {ua} | {key[qn]} |")
    table = "\n".join(lines)

    consignes_block = consignes.strip() if consignes.strip() else "(aucune)"

    return f"""# Rapport QCM

## Résumé
- Score: **{pct}%**
- Seuil: **{threshold}%**
- Statut: **{status}**

## Consignes appliquées
{consignes_block}

---

## Questions (QCM)
{qcm_text}

---

## Tes réponses vs Corrigé
{table}

---

## Corrigé (format brut)
{corrige_text}
"""


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

    # Répartir les questions
    per_chunk = max(1, args.n_questions // max(1, len(chunks)))
    leftover = args.n_questions - per_chunk * len(chunks)

    client = build_client()

    # ✅ Consignes depuis un doc (facultatif)
    consignes_final = ""
    if args.consignes:
        raw = read_file(args.consignes)
        if args.no_normalize_consignes:
            consignes_final = raw
        else:
            consignes_final = normalize_instructions(client, raw, lang=args.lang)
        print("✅ Consignes chargées.")

    print("🤖 Génération des questions...")
    blocks = []
    for idx, c in enumerate(chunks):
        n = per_chunk + (1 if idx < leftover else 0)
        blocks.append(
            generate_questions_for_chunk(
                client,
                c,
                n=n,
                lang=args.lang,
                instructions=consignes_final
            )
        )

    qcm_text = build_final_qcm(blocks, target_n=args.n_questions, seed=args.seed)
    if not qcm_text.strip():
        print("⚠️ QCM vide (problème génération).")
        return

    print("🧾 Génération du corrigé...")
    corrige = generate_answer_key(client, qcm_text, lang=args.lang)

    run_dir = make_run_dir(args.outdir)
    write_json(f"{run_dir}/sources.json", {"files": files, "errors": errors})
    write_text(f"{run_dir}/extracted.txt", full_text)
    write_text(f"{run_dir}/qcm.md", qcm_text)
    write_text(f"{run_dir}/corrige.md", corrige)
    write_text(f"{run_dir}/consignes.txt", consignes_final if consignes_final.strip() else "")

    score = 0.0
    user_answers: Dict[int, str] = {}

    if args.interactive:
        score, _, user_answers = run_interactive(qcm_text, corrige, pass_rate=args.pass_rate)

    if args.export_qa:
        report = build_qa_report_md(qcm_text, corrige, user_answers, score, pass_rate=args.pass_rate, consignes=consignes_final)
        write_text(f"{run_dir}/rapport_qcm.md", report)
        print(f"📄 Rapport généré: {run_dir}/rapport_qcm.md")

    print("\n✅ Terminé.")
    print(f"📁 Dossier: {run_dir}")
    print(f" - QCM     : {run_dir}/qcm.md")
    print(f" - Corrigé : {run_dir}/corrige.md")


if __name__ == "__main__":
    main()

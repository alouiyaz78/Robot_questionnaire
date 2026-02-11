import argparse
import random
from typing import List

from .loaders import list_files, read_file
from .chunker import chunk_text, normalize_text
from .qcm import build_client, generate_questions_for_chunk, merge_and_clean, generate_answer_key
from .io_utils import make_run_dir, write_text, write_json


def parse_args():
    p = argparse.ArgumentParser("robot-questionnaire")
    p.add_argument("--input", "-i", nargs="+", help="Fichiers ou dossiers", required=True)
    p.add_argument("--n-questions", "-n", type=int, default=15)
    p.add_argument("--max-chars", type=int, default=6000)
    p.add_argument("--overlap", type=int, default=400)
    p.add_argument("--lang", choices=["fr", "en"], default="fr")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main():
    args = parse_args()
    random.seed(args.seed)

    files = list_files(args.input)
    if not files:
        print("⚠️ Aucun fichier supporté trouvé (pdf/txt/docx).")
        return

    print(f"✅ {len(files)} fichier(s) détecté(s). Extraction...")
    texts: List[str] = []
    errors = []

    for f in files:
        try:
            t = read_file(f)
            if t.strip():
                texts.append(f"\n\n===== SOURCE: {f} =====\n\n{t}")
            else:
                errors.append({"file": f, "error": "Texte vide"})
        except Exception as e:
            errors.append({"file": f, "error": str(e)})

    full_text = normalize_text("\n".join(texts))
    if not full_text.strip():
        print("⚠️ Aucun texte exploitable.")
        return

    chunks = chunk_text(full_text, max_chars=args.max_chars, overlap=args.overlap)
    print(f"✅ Texte découpé en {len(chunks)} chunk(s).")

    # répartir le nb de questions sur les chunks
    per_chunk = max(1, args.n_questions // max(1, len(chunks)))
    leftover = args.n_questions - per_chunk * len(chunks)

    client = build_client()

    print("🤖 Génération des questions...")
    blocks = []
    for idx, c in enumerate(chunks):
        n = per_chunk + (1 if idx < leftover else 0)
        blocks.append(generate_questions_for_chunk(client, c, n=n, lang=args.lang))

    qcm_text = merge_and_clean(blocks, target_n=args.n_questions)
    corrige = generate_answer_key(client, qcm_text, lang=args.lang)

    outdir = make_run_dir()
    write_json(f"{outdir}/sources.json", {"files": files, "errors": errors})
    write_text(f"{outdir}/extracted.txt", full_text)
    write_text(f"{outdir}/qcm.md", qcm_text)
    write_text(f"{outdir}/corrige.md", corrige)

    print(f"\n✅ Terminé. Résultats dans: {outdir}")
    print(f"- qcm:      {outdir}/qcm.md")
    print(f"- corrigé:  {outdir}/corrige.md")


if __name__ == "__main__":
    main()

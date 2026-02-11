import re
import random
from typing import List
from openai import OpenAI


# ---------- OpenAI ----------
def build_client() -> OpenAI:
    import os
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY introuvable. Ajoute-la dans .env")

    return OpenAI(api_key=api_key)


# ---------- Génération ----------
def generate_questions_for_chunk(client: OpenAI, chunk: str, n: int, lang: str = "fr") -> str:
    prompt = f"""
Tu es un assistant pédagogique.
Génère {n} questions basées UNIQUEMENT sur le texte ci-dessous.

Contraintes:
- Langue: {lang}
- Mélange: QCM (4 options A/B/C/D) + Vrai/Faux
- Pas de corrigé dans cette étape
- Questions numérotées (ex: 1., 2., 3.)
- Questions concrètes, pas trop vagues

Texte:
\"\"\"{chunk}\"\"\"
""".strip()

    r = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=1400,
    )
    return r.choices[0].message.content.strip()


def generate_answer_key(client: OpenAI, qcm_text: str, lang: str = "fr") -> str:
    prompt = f"""
Voici un questionnaire:

{qcm_text}

Donne uniquement le corrigé au format strict:
1: A
2: Vrai
3: D
...

Langue: {lang}
""".strip()

    r = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=900,
    )
    return r.choices[0].message.content.strip()


# ---------- Assemblage "pro" ----------
def merge_and_clean(question_blocks: List[str], target_n: int) -> str:
    # (Gardé si jamais, mais on utilise build_final_qcm dans le CLI)
    merged = "\n\n".join(q for q in question_blocks if q.strip()).strip()
    return merged if merged else ""


def extract_questions(qcm_text: str) -> List[str]:
    """
    Extrait les blocs de questions numérotées.
    Un bloc commence par "12." et s'étend jusqu'avant la prochaine question.
    """
    pattern = r"(?m)^\d+\.\s.*(?:\n(?!^\d+\.).*)*"
    matches = re.findall(pattern, qcm_text)
    return [m.strip() for m in matches if m.strip()]


def renumber_questions(questions: List[str]) -> str:
    """
    Renumérote proprement les questions de 1..N
    """
    out = []
    for i, q in enumerate(questions, start=1):
        q = re.sub(r"(?m)^\d+\.", f"{i}.", q, count=1)
        out.append(q.strip())
    return "\n\n".join(out)


def build_final_qcm(question_blocks: List[str], target_n: int, seed: int = 42) -> str:
    """
    Fusionne les blocs, extrait toutes les questions,
    mélange, sélectionne target_n, renumérote.
    """
    all_text = "\n\n".join(question_blocks)
    questions = extract_questions(all_text)

    random.seed(seed)
    random.shuffle(questions)

    final_questions = questions[:target_n]
    return renumber_questions(final_questions)

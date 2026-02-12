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


def normalize_instructions(client: OpenAI, raw: str, lang: str = "fr") -> str:
    """
    Transforme un document de consignes (parfois long) en règles courtes et actionnables,
    pour éviter que le prompt devienne trop lourd / flou.
    """
    if not raw or not raw.strip():
        return ""

    prompt = f"""
Tu vas transformer des consignes brutes en règles STRICTES pour générer un QCM.

Objectif: produire une liste de règles courtes, claires, sans blabla.
Langue: {lang}

Format de sortie (respecte EXACTEMENT ce format):
- Interdits: ...
- Autorisés: ...
- Priorités: ...
- Niveau: ...
- Style: ...

Consignes brutes:
\"\"\"{raw}\"\"\"
""".strip()

    r = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=500,
    )
    return r.choices[0].message.content.strip()


# ---------- Génération ----------
def generate_questions_for_chunk(
    client: OpenAI,
    chunk: str,
    n: int,
    lang: str = "fr",
    instructions: str = "",
) -> str:
    instructions_block = ""
    if instructions and instructions.strip():
        instructions_block = f"""
CONSIGNES À RESPECTER (prioritaires):
{instructions.strip()}
"""

    prompt = f"""
Tu es un assistant pédagogique.
Génère {n} questions basées UNIQUEMENT sur le texte ci-dessous.

{instructions_block}

Contraintes générales:
- Langue: {lang}
- Mélange: QCM (4 options A/B/C/D) + Vrai/Faux
- Pas de corrigé dans cette étape
- Questions numérotées (ex: 1., 2., 3.)
- Si une consigne interdit un thème, n’inclus aucune question sur ce thème.
- Ne pose pas de questions hors du texte.
- Évite les répétitions.

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
def extract_questions(qcm_text: str) -> List[str]:
    pattern = r"(?m)^\d+\.\s.*(?:\n(?!^\d+\.).*)*"
    matches = re.findall(pattern, qcm_text)
    return [m.strip() for m in matches if m.strip()]


def renumber_questions(questions: List[str]) -> str:
    out = []
    for i, q in enumerate(questions, start=1):
        q = re.sub(r"(?m)^\d+\.", f"{i}.", q, count=1)
        out.append(q.strip())
    return "\n\n".join(out)


def build_final_qcm(question_blocks: List[str], target_n: int, seed: int = 42) -> str:
    all_text = "\n\n".join(question_blocks)
    questions = extract_questions(all_text)

    random.seed(seed)
    random.shuffle(questions)

    final_questions = questions[:target_n]
    return renumber_questions(final_questions)

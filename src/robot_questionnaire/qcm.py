import json
import random
from typing import Any, Dict, List
from openai import OpenAI


def build_client() -> OpenAI:
    import os
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY introuvable. Ajoute-la dans .env")

    return OpenAI(api_key=api_key)


def normalize_instructions(client: OpenAI, raw: str, lang: str = "fr") -> str:
    if not raw or not raw.strip():
        return ""

    prompt = f"""
Transforme des consignes brutes en règles STRICTES pour générer un questionnaire.

Langue: {lang}
Format EXACT:
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


def _safe_json_load(s: str) -> Dict[str, Any]:
    s = s.strip()
    # Nettoyage minimal si le modèle ajoute du texte autour
    first = s.find("{")
    last = s.rfind("}")
    if first != -1 and last != -1 and last > first:
        s = s[first:last + 1]
    return json.loads(s)


def generate_exam_questions_for_chunk(
    client: OpenAI,
    chunk: str,
    n: int,
    lang: str = "fr",
    instructions: str = "",
) -> List[Dict[str, Any]]:
    """
    Génère une liste de questions (dict) au format JSON.
    Types supportés:
      - true_false
      - mcq_single
      - multi_select
      - matching
      
    """
    rules = instructions.strip()
    rules_block = f"\nCONSIGNES À RESPECTER (prioritaires):\n{rules}\n" if rules else ""

    prompt = f"""
Tu es un générateur d'examens (style Moodle).

{rules_block}

Texte source (tu dois rester dans ce contenu):
\"\"\"{chunk}\"\"\"

Génère {n} questions au FORMAT JSON STRICT (aucun texte hors JSON).

Schéma:
{{
  "questions": [
    {{
      "type": "true_false" | "mcq_single" | "multi_select" | "matching" | "open_long",
      "points": 2,
      "text": "question",
      // Pour mcq_single / multi_select / true_false:
      "options": ["..."],
      // Pour matching:
      "left": ["item1","item2","item3"],
      "right": ["choice1","choice2","choice3"],
      
      "rubric": "attendu / corrigé synthétique",
      // Réponse:
      "answer": "Vrai" | "Faux" | "Option exacte" | ["Option1","Option2"] | {{ "left_item":"right_item" }} | "Rubric"
    }}
  ]
}}

Contraintes:
- Mélange de types: inclure TF + QCM + scénario + au moins 1 matching si possible
- Pour scenario: mets le mot 'SCÉNARIO :' au début de text
- Pas de doublons, pas de questions triviales
- Les options doivent être en texte (pas A/B/C/D). Le programme gère l'affichage.
""".strip()

    r = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=1800,
    )

    data = _safe_json_load(r.choices[0].message.content)
    qs = data.get("questions", [])
    # Filtre minimal
    out = []
    for q in qs:
        if isinstance(q, dict) and q.get("type") and q.get("text"):
            out.append(q)
    return out


def build_final_exam(questions_blocks: List[List[Dict[str, Any]]], target_n: int, seed: int = 42) -> List[Dict[str, Any]]:
    all_qs: List[Dict[str, Any]] = []
    for block in questions_blocks:
        all_qs.extend(block)

    random.seed(seed)
    random.shuffle(all_qs)

    # garde target_n
    final = all_qs[:target_n]

    # normalise points si absent
    for q in final:
        q.setdefault("points", 2)

        # true_false options
        if q.get("type") == "true_false" and not q.get("options"):
            q["options"] = ["Vrai", "Faux"]

    return final

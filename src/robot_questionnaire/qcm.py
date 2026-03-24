import json
import random
import re
from difflib import SequenceMatcher
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
    first = s.find("{")
    last = s.rfind("}")
    if first != -1 and last != -1 and last > first:
        s = s[first:last + 1]
    return json.loads(s)


def normalize_question_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def deduplicate_questions(questions: List[Dict[str, Any]], similarity_threshold: float = 0.88) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    seen: List[str] = []

    for q in questions:
        txt = normalize_question_text(q.get("text", ""))
        if not txt:
            continue

        is_dup = False
        for prev in seen:
            ratio = SequenceMatcher(None, txt, prev).ratio()
            if ratio >= similarity_threshold:
                is_dup = True
                break

        if not is_dup:
            kept.append(q)
            seen.append(txt)

    return kept


def filter_non_autonomous_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Supprime les questions qui semblent dépendre d'un contexte externe non fourni.
    """
    banned_patterns = [
        r"\bdans l[’']exemple\b",
        r"\bdans la figure\b",
        r"\bdans le tableau\b",
        r"\bdans la capture\b",
        r"\bcomme montr[ée] pr[ée]c[ée]demment\b",
        r"\bci-dessus\b",
        r"\bvoir la figure\b",
        r"\bvoir le tableau\b",
    ]

    out = []
    for q in questions:
        text = q.get("text", "")
        lowered = text.lower()

        banned = any(re.search(p, lowered) for p in banned_patterns)

        # Si la question contient explicitement des données utiles, on la garde
        contains_inline_data = any(token in text for token in [":", "→", "=>", "A)", "1)", "2)", "3)"])

        if banned and not contains_inline_data:
            continue

        out.append(q)

    return out


def _difficulty_rules(difficulty: str, lang: str) -> str:
    if difficulty == "facile":
        return f"""
- Difficulté demandée: facile
- Générer des questions de compréhension directe, définitions, reconnaissance de concepts, vrai/faux simples
- Limiter les scénarios complexes
- Éviter les comparaisons trop techniques
- Niveau adapté à une première lecture du cours
""".strip()

    if difficulty == "difficile":
        return f"""
- Difficulté demandée: difficile
- Générer des questions d’interprétation, de comparaison, de choix méthodologique et d’application avancée
- Inclure plusieurs questions comparant deux modèles, deux méthodes ou deux concepts
- Utiliser des scénarios plus exigeants
- Les distracteurs doivent être plausibles
- Éviter les questions purement mémorielles
""".strip()

    return f"""
- Difficulté demandée: moyen
- Générer des questions d’application, scénarios courts, compréhension fine et comparaisons simples
- Mélanger compréhension et raisonnement
- Niveau adapté à un étudiant ayant révisé le cours
""".strip()


def generate_exam_questions_for_chunk(
    client: OpenAI,
    chunk: str,
    n: int,
    lang: str = "fr",
    instructions: str = "",
    difficulty: str = "moyen",
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
    difficulty_block = _difficulty_rules(difficulty, lang)

    prompt = f"""
Tu es un générateur d'examens (style Moodle).

{rules_block}

{difficulty_block}

Texte source (tu dois rester dans ce contenu):
\"\"\"{chunk}\"\"\"

Génère {n} questions au FORMAT JSON STRICT (aucun texte hors JSON).

Schéma:
{{
  "questions": [
    {{
      "type": "true_false" | "mcq_single" | "multi_select" | "matching",
      "points": 2,
      "text": "question",
      "options": ["..."],
      "left": ["item1","item2","item3"],
      "right": ["choice1","choice2","choice3"],
      "answer": "Vrai" | "Faux" | "Option exacte" | ["Option1","Option2"] | {{ "left_item":"right_item" }}
    }}
  ]
}}

Contraintes globales:
- Interdit: questions ouvertes, réponses libres, dissertations
- Chaque question doit être autonome
- Ne jamais utiliser "dans l’exemple", "dans la figure", "dans le tableau", "dans la capture" sauf si les données nécessaires sont incluses dans l’énoncé
- Si une question dépend de données, inclure explicitement ces données dans la question
- Ne pose pas de question impossible à résoudre sans contexte externe
- Évite les répétitions
- Varie les formulations et les thèmes

Variété demandée:
- Inclure un mélange de:
  * vrai/faux
  * QCM à réponse unique
  * QCM à réponses multiples
  * association (matching)
  * scénarios courts autonomes
  * questions de comparaison entre deux modèles, deux méthodes ou deux concepts quand le cours s’y prête

Exemples de comparaisons autorisées si le texte le permet:
- deux modèles
- deux méthodes
- deux métriques
- deux algorithmes
- deux notions proches mais différentes

Règles de qualité:
- Les distracteurs doivent être plausibles
- Les questions ne doivent pas être triviales
- Pas deux questions sur exactement la même idée
- Les options doivent être en texte, pas en A/B/C/D
- Pour les questions de type matching, produire exactement 3 ou 4 associations cohérentes
- Pour les scénarios, écrire "SCÉNARIO :" au début du texte
""".strip()

    r = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=2200,
    )

    data = _safe_json_load(r.choices[0].message.content)
    qs = data.get("questions", [])

    out = []
    for q in qs:
        if isinstance(q, dict) and q.get("type") and q.get("text"):
            out.append(q)

    return out


def build_final_exam(
    questions_blocks: List[List[Dict[str, Any]]],
    target_n: int,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    all_qs: List[Dict[str, Any]] = []
    for block in questions_blocks:
        all_qs.extend(block)

    # sécurité: filtrage qualité
    all_qs = [q for q in all_qs if q.get("type") in {"true_false", "mcq_single", "multi_select", "matching"}]
    all_qs = filter_non_autonomous_questions(all_qs)
    all_qs = deduplicate_questions(all_qs, similarity_threshold=0.88)

    random.seed(seed)
    random.shuffle(all_qs)

    final = all_qs[:target_n]

    for q in final:
        q.setdefault("points", 2)

        if q.get("type") == "true_false" and not q.get("options"):
            q["options"] = ["Vrai", "Faux"]

    return final
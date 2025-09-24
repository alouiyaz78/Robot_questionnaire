import os
from openai import OpenAI
import PyPDF2
import random
from dotenv import load_dotenv


load_dotenv()  # Charge les variables du fichier .env
api_key = os.getenv("OPENAI_API_KEY")
# Créer le client OpenAI
client = OpenAI(api_key)



def lire_documents(dossier="Data"):
    """Lit tous les fichiers PDF et TXT du dossier et retourne un texte concaténé"""
    texte_complet = ""
    for fichier in os.listdir(dossier):
        chemin = os.path.join(dossier, fichier)
        if fichier.endswith(".pdf"):
            with open(chemin, "rb") as f:
                lecteur = PyPDF2.PdfReader(f)
                for page in lecteur.pages:
                    texte_complet += page.extract_text() + "\n"
        elif fichier.endswith(".txt"):
            with open(chemin, "r", encoding="utf-8") as f:
                texte_complet += f.read() + "\n"
    return texte_complet


def generer_qcm(texte, nombre_questions=15):
    """Génère un QCM avec des questions choix multiples et vrai/faux"""
    prompt = f"""
    Crée un questionnaire de {nombre_questions} questions basé sur ce texte :
    {texte}

    IMPORTANT :
    - Mélange des questions à choix multiples (4 options : A, B, C, D) et des questions Vrai/Faux.
    - Ne donne pas les réponses correctes dans cette étape.
    - Numérote les questions.
    """

    response = client.chat.completions.create(
        model="gpt-4.1-mini",   # ou gpt-5-mini si dispo
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=1500
    )

    return response.choices[0].message.content.strip()


def generer_corrige(texte_qcm):
    """Demande au modèle de donner uniquement les bonnes réponses du QCM"""
    prompt = f"""
    Voici un QCM généré :

    {texte_qcm}

    Donne uniquement la liste des réponses correctes au format :
    1: A
    2: Vrai
    3: C
    4: Faux
    ...
    """

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=800
    )

    return response.choices[0].message.content.strip()


def corriger_reponses(reponses_utilisateur, corrige):
    """Compare les réponses utilisateur avec le corrigé"""
    bonnes_reponses = {}
    for ligne in corrige.splitlines():
        try:
            num, rep = ligne.split(":")
            bonnes_reponses[int(num.strip())] = rep.strip().capitalize()
        except:
            continue

    score = 0
    erreurs = []
    for i, rep_user in enumerate(reponses_utilisateur, start=1):
        if i in bonnes_reponses:
            if rep_user.strip().capitalize() == bonnes_reponses[i]:
                score += 1
            else:
                erreurs.append((i, rep_user.strip(), bonnes_reponses[i]))

    return score, erreurs, len(bonnes_reponses)


def lancer_questionnaire(texte_cours):
    """Lance un questionnaire complet"""
    # Génération du QCM avec entre 10 et 20 questions
    nombre_questions = random.randint(10, 20)
    qcm = generer_qcm(texte_cours, nombre_questions)
    print("\n=== Questionnaire ===\n")
    print(qcm)

    # Récupération du corrigé
    corrige = generer_corrige(qcm)

    # Réponses utilisateur
    print("\n=== Entrez vos réponses ===")
    reponses_utilisateur = []
    for i in range(1, len(corrige.splitlines()) + 1):
        rep = input(f"Votre réponse à la question {i} : ")
        reponses_utilisateur.append(rep)

    # Correction
    score, erreurs, total = corriger_reponses(reponses_utilisateur, corrige)

    print("\n=== Résultats ===")
    print(f"Score : {score}/{total}")
    if erreurs:
        print("Erreurs :")
        for num, rep_user, rep_correcte in erreurs:
            print(f"  Q{num}: Votre réponse = {rep_user}, Bonne réponse = {rep_correcte}")


if __name__ == "__main__":
    texte_cours = lire_documents("Data")

    if not texte_cours.strip():
        print("⚠️ Aucun texte trouvé dans le dossier Data !")
        exit()

    while True:
        lancer_questionnaire(texte_cours)
        choix = input("\nAppuyez sur [R] pour refaire un questionnaire ou [Q] pour quitter : ").strip().upper()
        if choix == "Q":
            print("✅ Merci d'avoir utilisé le robot questionnaire !")
            break

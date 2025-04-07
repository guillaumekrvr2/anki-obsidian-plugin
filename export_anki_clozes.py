#!/usr/bin/env python3
import requests
import os
import re
import html
import hashlib
from bs4 import BeautifulSoup # Toujours utile pour extraire la 1ère ligne

# === Configuration ===
output_dir = os.path.expanduser("~/Downloads/Documents perso/Obsidian")
index_note_path = os.path.join(output_dir, "Anki.md")

anki_field_name = "Texte" # Nom du champ Anki contenant le HTML principal
title_max_length = 95 # Longueur max pour le titre extrait

# Mettre ici l'ID d'une note à tester, ou None pour tout exporter (jusqu'à max_notes)
note_id_target = None # Mettre un ID ici pour tester une seule note spécifique

# === Fonctions ===

def remove_cloze_keep_html(text):
    """Supprime les marqueurs d'occlusion Anki {{c...}} en gardant le contenu."""
    # Utilise une regex non-gourmande (.*?) pour gérer les cas multiples sur une ligne
    # S'assure de ne pas capturer les "hints" (::hint) comme partie du contenu principal
    return re.sub(r"{{c\d+::(.*?)(::.*?)?}}", r"\1", text, flags=re.DOTALL)

def sanitize_filename(title, max_length=100):
    """Nettoie une chaîne pour l'utiliser comme nom de fichier."""
    title = title.replace("/", "-").replace(":", "-").replace("\\", "-")
    title = re.sub(r'[<>:"/\\|?*]', '', title)
    title = re.sub(r'[\x00-\x1f\x7f]', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    if not title or title.strip('.') == '':
        return "Sans titre" # Retourne "Sans titre" si vide après nettoyage
    return title[:max_length].strip() # Limite la longueur finale après nettoyage

def extract_title_from_html(html_content, max_len):
    """
    Extrait la première ligne de texte significative du HTML pour servir de titre.
    Tronque si nécessaire.
    """
    if not html_content:
        return "Sans titre"

    try:
        soup = BeautifulSoup(html_content, 'lxml')
        # Essayer d'extraire le texte en préservant certains sauts de ligne comme séparateurs
        text_content = soup.get_text(separator='\n', strip=True)

        if not text_content: # Si aucun texte n'est trouvé
             return "Sans titre"

        # Trouver la première ligne non vide
        first_line = ""
        for line in text_content.split('\n'):
            stripped_line = line.strip()
            if stripped_line: # Si la ligne n'est pas vide après suppression des espaces
                first_line = stripped_line
                break # On a trouvé la première ligne significative

        if not first_line: # Si toujours vide après la boucle
            return "Sans titre"

        # Nettoyer les entités HTML résiduelles
        first_line = html.unescape(first_line)

        # Tronquer si nécessaire
        if len(first_line) > max_len:
            return first_line[:max_len] + "..."
        else:
            return first_line

    except Exception as e:
        # En cas d'erreur de parsing ou autre, retourner un titre par défaut
        print(f"⚠️ Erreur lors de l'extraction du titre : {e}. Utilisation de 'Sans titre'.")
        return "Sans titre"


def get_note_ids():
    """Récupère les IDs des notes depuis AnkiConnect pour tous les paquets dont le nom contient 'Fiches'."""
    if note_id_target:
        print(f"ℹ️ Ciblage de la note unique ID : {note_id_target}")
        return [note_id_target]

    print("🔍 Recherche de toutes les notes dont le paquet contient 'Fiches'...")
    payload = {
        "action": "findNotes",
        "version": 6,
        "params": { "query": "deck:*Fiches*" }
    }
    try:
        r = requests.post("http://localhost:8765", json=payload, timeout=10)
        r.raise_for_status()
        result = r.json().get("result", [])
        print(f"🧠 {len(result)} IDs de notes trouvés dans les paquets contenant 'Fiches'.")
        return result
    except requests.exceptions.ConnectionError:
        print("❌ Erreur : Impossible de se connecter à AnkiConnect sur http://localhost:8765.")
        print("   Vérifiez qu'Anki est lancé et que l'extension AnkiConnect est installée et activée.")
        return None
    except requests.exceptions.Timeout:
        print("❌ Erreur : Timeout lors de la connexion à AnkiConnect.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur de requête AnkiConnect (findNotes) : {e}")
        return None
    except Exception as e:
        print(f"❌ Erreur inattendue lors de la récupération des IDs : {e}")
        return None

def get_notes_details(note_ids):
    """Récupère les informations détaillées des notes spécifiées."""
    if not note_ids:
        return []
    print(f"ℹ️ Récupération des détails pour {len(note_ids)} notes...")
    payload = {
        "action": "notesInfo",
        "version": 6,
        "params": { "notes": note_ids }
    }
    try:
        r = requests.post("http://localhost:8765", json=payload, timeout=30)
        r.raise_for_status()
        result = r.json().get("result", [])
        print(f"✅ Détails récupérés pour {len(result)} notes.")
        return result
    except requests.exceptions.ConnectionError:
        print("❌ Erreur : Impossible de se connecter à AnkiConnect sur http://localhost:8765.")
        return None
    except requests.exceptions.Timeout:
        print("❌ Erreur : Timeout lors de la récupération des détails des notes.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur de requête AnkiConnect (notesInfo) : {e}")
        return None
    except Exception as e:
        print(f"❌ Erreur inattendue lors de la récupération des détails : {e}")
        return None


def export_notes(notes):
    """Exporte les notes Anki fournies en fichiers Markdown (corps en HTML brut)."""
    if not notes:
        print("⚠️ Aucune note à exporter.")
        return

    os.makedirs(output_dir, exist_ok=True)
    backlinks = []
    seen_filenames = set()
    seen_hashes = set()
    exported_count = 0

    print(f"🚀 Début de l'exportation vers : {output_dir}")

    for note in notes:
        note_id = note.get("noteId")
        if not note_id:
            print(f"⚠️ Note ignorée (pas d'ID)")
            continue

        raw_html_original = note.get("fields", {}).get(anki_field_name, {}).get("value", "")
        if not raw_html_original:
            print(f"⚠️ Note {note_id} ignorée (champ '{anki_field_name}' vide ou manquant).")
            continue

        # 1. Supprimer les occlusions pour le corps ET pour l'extraction du titre
        html_body_no_cloze = remove_cloze_keep_html(raw_html_original)

        # 2. Extraire le titre à partir du HTML nettoyé des occlusions
        title = extract_title_from_html(html_body_no_cloze, title_max_length)

        # 3. Récupérer les tags Anki
        tags_list = note.get("tags", [])
        tags_md_line = "Tags: " + " ".join(f"#{tag}" for tag in tags_list if tag) if tags_list else ""

        # 4. Le contenu du fichier est le HTML (sans occlusions) + la ligne de tags
        #    On ajoute une séparation claire pour ne pas mélanger HTML et tags Markdown
        content_to_write = f"{html_body_no_cloze}\n\n---\n\n{tags_md_line}".strip()

        # 5. Hash unique basé sur le contenu HTML + ID
        #    Utiliser html_body_no_cloze car c'est ce qui sera écrit (hors tags)
        content_hash = hashlib.md5((html_body_no_cloze + str(note_id)).encode("utf-8")).hexdigest()
        if content_hash in seen_hashes:
            print(f"ℹ️ Note {note_id} déjà traitée (hash identique), ignorée.")
            continue
        seen_hashes.add(content_hash)

        # 6. Gestion du nom de fichier (basé sur le titre extrait et tronqué)
        base_filename = sanitize_filename(title) # title est déjà tronqué si besoin
        filename_final = base_filename
        suffix = 1
        # Utilise os.path.exists pour vérifier les fichiers réels, pas juste les noms vus
        while os.path.exists(os.path.join(output_dir, f"{filename_final}.md")):
            # Gérer spécifiquement "Sans titre" pour éviter "Sans titre_1_1" etc.
            if base_filename.startswith("Sans titre"):
                 # Si on a déjà un compteur (ex: "Sans titre 2"), on l'incrémente
                 match = re.match(r"^(Sans titre)(?: (\d+))?$", base_filename)
                 current_num = int(match.group(2) or 0) if match else 0
                 filename_final = f"Sans titre {current_num + suffix}"
            else:
                 filename_final = f"{base_filename}_{suffix}"
            suffix += 1

        filepath = os.path.join(output_dir, f"{filename_final}.md")

        # 7. Écrire le fichier
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content_to_write)
            print(f"✅ Note {note_id} exportée : {filepath}")
            backlinks.append(f"- [[{filename_final}]]") # Lien Obsidian utilise le nom de fichier sans .md
            exported_count += 1
        except OSError as e:
            print(f"❌ Erreur lors de l'écriture du fichier {filepath} : {e}")
        except Exception as e:
             print(f"❌ Erreur inattendue lors de l'écriture du fichier {filepath} : {e}")


    print(f"\n✨ Exportation terminée. {exported_count} note(s) écrite(s).")

    # Écrire le fichier d'index
    if backlinks:
        try:
            with open(index_note_path, "w", encoding="utf-8") as f:
                f.write("# 📘 Anki Index\n\n")
                f.write("\n".join(sorted(backlinks)))
            print(f"📎 Fichier d'index créé/mis à jour : {index_note_path}")
        except OSError as e:
            print(f"❌ Erreur lors de l'écriture du fichier d'index {index_note_path} : {e}")
    else:
        print("ℹ️ Aucun backlink à ajouter au fichier d'index.")

def main():
    """Fonction principale du script."""
    print("--- Début du script d'exportation Anki vers Obsidian (HTML brut) ---")
    note_ids = get_note_ids()

    if note_ids is None:
         print("❌ Arrêt du script en raison d'une erreur de récupération des IDs.")
         return

    if not note_ids:
        print("ℹ️ Aucune note trouvée ou sélectionnée. Fin du script.")
        return

    notes_data = get_notes_details(note_ids)

    if notes_data is None:
        print("❌ Arrêt du script en raison d'une erreur de récupération des détails des notes.")
        return

    export_notes(notes_data)
    print("--- Fin du script ---")

if __name__ == "__main__":
    main()
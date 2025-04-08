#!/usr/bin/env python3
import requests
import os
import re
import html
import hashlib
from bs4 import BeautifulSoup  # Toujours utile pour extraire la 1ère ligne

# === Configuration ===
output_dir = os.path.expanduser("~/Downloads/Documents perso/Obsidian")
index_note_path = os.path.join(output_dir, "Anki.md")

anki_field_name = "Texte"      # Nom du champ Anki contenant le HTML principal (pour les cartes 'texte à trou')
title_max_length = 95          # Longueur max pour le titre extrait

# Pour cibler le deck dont le titre contient "Fiches"
deck_query = "deck:*Fiches*"

# Mettre ici l'ID d'une note à tester, ou None pour tout exporter
note_id_target = None         # Mettre un ID ici pour tester une seule note spécifique

# Ensemble pour stocker les noms des fiches de tag (pour l'index global)
tag_notes_set = set()

# Définition des types de notes traitées en mode "recto verso"
recto_verso_types = {
    "basique (carte inversée optionnelle)",
    "basique (saisissez la réponse)",
    "généralités (deux sens)",
    "basique"
}

# === Fonctions ===

def remove_cloze_keep_html(text):
    """Supprime les marqueurs d'occlusion Anki {{c...}} en gardant le contenu."""
    return re.sub(r"{{c\d+::(.*?)(::.*?)?}}", r"\1", text, flags=re.DOTALL)

def sanitize_filename(title, max_length=100):
    """Nettoie une chaîne pour l'utiliser comme nom de fichier."""
    title = title.replace("/", "-").replace(":", "-").replace("\\", "-")
    title = re.sub(r'[<>:"/\\|?*]', '', title)
    title = re.sub(r'[\x00-\x1f\x7f]', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    if not title or title.strip('.') == '':
        return "Sans titre"
    return title[:max_length].strip()

def extract_title_from_html(html_content, max_len):
    """
    Extrait la première ligne de texte significative du HTML pour servir de titre.
    Tronque si nécessaire.
    """
    if not html_content:
        return "Sans titre"
    try:
        soup = BeautifulSoup(html_content, 'lxml')
        text_content = soup.get_text(separator='\n', strip=True)
        if not text_content:
            return "Sans titre"
        first_line = ""
        for line in text_content.split('\n'):
            stripped_line = line.strip()
            if stripped_line:
                first_line = stripped_line
                break
        if not first_line:
            return "Sans titre"
        first_line = html.unescape(first_line)
        if len(first_line) > max_len:
            return first_line[:max_len] + "..."
        else:
            return first_line
    except Exception as e:
        print(f"⚠️ Erreur lors de l'extraction du titre : {e}. Utilisation de 'Sans titre'.")
        return "Sans titre"

def get_note_ids():
    """Récupère les IDs des notes depuis AnkiConnect pour les decks dont le titre contient 'Fiches'."""
    if note_id_target:
        print(f"ℹ️ Ciblage de la note unique ID : {note_id_target}")
        return [note_id_target]
    print(f"🔍 Recherche de toutes les notes avec le deck correspondant à '{deck_query}'...")
    payload = {
        "action": "findNotes",
        "version": 6,
        "params": { "query": deck_query }
    }
    try:
        r = requests.post("http://localhost:8765", json=payload, timeout=10)
        r.raise_for_status()
        result = r.json().get("result", [])
        print(f"🧠 {len(result)} IDs de notes trouvés pour la requête '{deck_query}'.")
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
        print(f"❌ Erreur inattendue lors de la récupération des détails des notes : {e}")
        return None

def update_tag_file(tag_name, note_link):
    """
    Crée ou met à jour la note de tag (ex : Histoire.md) en y ajoutant le lien vers la note.
    Cette fonction s'assure également que le fichier se termine par le hashtag correspondant (en minuscules),
    par exemple "#histoire" pour le tag "Histoire".
    """
    tag_clean = tag_name if tag_name else "Sans tag"
    tag_filename = sanitize_filename(tag_clean)
    tag_filepath = os.path.join(output_dir, f"{tag_filename}.md")
    tag_notes_set.add(tag_filename)

    tag_hashtag = f"#{tag_clean.lower()}"

    lines = []
    if os.path.exists(tag_filepath):
        with open(tag_filepath, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        while lines and lines[-1].strip() == "":
            lines.pop()
        if lines and lines[-1].strip() == tag_hashtag:
            lines.pop()
    else:
        lines = [f"# {tag_clean}", "", "Liste des notes liées:"]

    note_line = f"- [[{note_link}]]"
    if note_line not in lines:
        lines.append(note_line)

    lines.append("")
    lines.append(tag_hashtag)

    new_content = "\n".join(lines) + "\n"
    with open(tag_filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

def export_notes(notes):
    """Exporte les notes Anki en fichiers Markdown et met à jour les fiches de tag.
       Prend en compte deux types de cartes :
       - 'texte à trou' : traitement sur le champ défini par anki_field_name.
       - 'recto verso' : si le type de carte est l'un des suivants :
            * Basique (carte inversée optionnelle)
            * Basique (saisissez la réponse)
            * Généralités (deux sens)
            * Basique
         alors le champ 'Recto' est utilisé pour extraire le titre et tous les autres champs (par ex. 'Verso') sont concaténés pour former le corps.
       Les autres types de cartes sont ignorés.
    """
    if not notes:
        print("⚠️ Aucune note à exporter.")
        return

    os.makedirs(output_dir, exist_ok=True)
    seen_hashes = set()
    exported_count = 0

    print(f"🚀 Début de l'exportation vers : {output_dir}")

    for note in notes:
        note_id = note.get("noteId")
        if not note_id:
            print("⚠️ Note ignorée (pas d'ID)")
            continue

        model_name = note.get("modelName", "")
        if not model_name:
            print(f"⚠️ Note {note_id} ignorée (pas de type de carte).")
            continue

        model_lower = model_name.lower()

        # Préparer les tags
        tags_list = note.get("tags", [])
        if not tags_list:
            tags_list = [None]
        tags_md_line = "Tags: " + " ".join(f"#{tag}" for tag in tags_list if tag) if any(tags_list) else ""

        # Traitement selon le type de note
        if "texte à trou" in model_lower:
            raw_html_original = note.get("fields", {}).get(anki_field_name, {}).get("value", "")
            if not raw_html_original:
                print(f"⚠️ Note {note_id} ignorée (champ '{anki_field_name}' vide ou manquant).")
                continue
            html_body_no_cloze = remove_cloze_keep_html(raw_html_original)
            title = extract_title_from_html(html_body_no_cloze, title_max_length)
            content_to_write = f"{html_body_no_cloze}\n\n---\n\n{tags_md_line}".strip()
        elif model_lower in recto_verso_types:
            fields = note.get("fields", {})
            recto_field = fields.get("Recto", {}).get("value", "")
            if not recto_field:
                print(f"⚠️ Note {note_id} ignorée (champ 'Recto' vide ou manquant).")
                continue
            title = extract_title_from_html(recto_field, title_max_length)
            verso_parts = []
            for key, field in fields.items():
                if key.lower() == "recto":
                    continue
                value = field.get("value", "")
                if value:
                    verso_parts.append(value)
            if not verso_parts:
                print(f"⚠️ Note {note_id} ignorée (aucun contenu trouvé pour le verso).")
                continue
            body_html = "\n\n".join(verso_parts)
            content_to_write = f"{body_html}\n\n---\n\n{tags_md_line}".strip()
        else:
            print(f"ℹ️ Note {note_id} ignorée car son type de carte ({model_name}) n'est pas supporté.")
            continue

        content_hash = hashlib.md5((content_to_write + str(note_id)).encode("utf-8")).hexdigest()
        if content_hash in seen_hashes:
            print(f"ℹ️ Note {note_id} déjà traitée (hash identique), ignorée.")
            continue
        seen_hashes.add(content_hash)

        base_filename = sanitize_filename(title)
        filename_final = base_filename
        suffix = 1
        while os.path.exists(os.path.join(output_dir, f"{filename_final}.md")):
            if base_filename.startswith("Sans titre"):
                match = re.match(r"^(Sans titre)(?: (\d+))?$", base_filename)
                current_num = int(match.group(2) or 0) if match else 0
                filename_final = f"Sans titre {current_num + suffix}"
            else:
                filename_final = f"{base_filename}_{suffix}"
            suffix += 1

        filepath = os.path.join(output_dir, f"{filename_final}.md")

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content_to_write)
            print(f"✅ Note {note_id} exportée : {filepath}")
            exported_count += 1
        except OSError as e:
            print(f"❌ Erreur lors de l'écriture du fichier {filepath} : {e}")
            continue
        except Exception as e:
            print(f"❌ Erreur inattendue lors de l'écriture du fichier {filepath} : {e}")
            continue

        for tag in tags_list:
            update_tag_file(tag, filename_final)

    print(f"\n✨ Exportation terminée. {exported_count} note(s) écrite(s).")

    if tag_notes_set:
        index_lines = ["# 📘 Index des fiches de tag", "", "- [[Index]]", ""]
        for tag_note in sorted(tag_notes_set):
            index_lines.append(f"- [[{tag_note}]]")
        try:
            with open(index_note_path, "w", encoding="utf-8") as f:
                f.write("\n".join(index_lines))
            print(f"📎 Fichier d'index créé/mis à jour : {index_note_path}")
        except OSError as e:
            print(f"❌ Erreur lors de l'écriture du fichier d'index {index_note_path} : {e}")
    else:
        print("ℹ️ Aucune fiche de tag à indexer.")

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

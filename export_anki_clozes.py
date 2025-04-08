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

anki_field_name = "Texte"      # Nom du champ Anki contenant le HTML principal
title_max_length = 95          # Longueur max pour le titre extrait

# Mettre ici l'ID d'une note à tester, ou None pour tout exporter (jusqu'à max_notes)
note_id_target = None         # Mettre un ID ici pour tester une seule note spécifique

# Ensemble pour stocker les noms des fiches de tag (pour l'index global)
tag_notes_set = set()

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
        print(f"❌ Erreur inattendue lors de la récupération des détails des notes : {e}")
        return None

def update_tag_file(tag_name, note_link):
    """
    Crée ou met à jour la note de tag (ex : Histoire.md) en y ajoutant le lien vers la note.
    En plus, cette fonction s'assure que le fichier se termine par le hashtag correspondant (en minuscules),
    par exemple "#histoire" pour le tag "Histoire".
    """
    # Pour une note sans tag, on utilise "Sans tag"
    tag_clean = tag_name if tag_name else "Sans tag"
    tag_filename = sanitize_filename(tag_clean)
    tag_filepath = os.path.join(output_dir, f"{tag_filename}.md")
    # Ajout du tag dans l'ensemble global (pour l'index)
    tag_notes_set.add(tag_filename)

    # Définir la ligne de hashtag (en minuscules)
    tag_hashtag = f"#{tag_clean.lower()}"

    lines = []
    if os.path.exists(tag_filepath):
        with open(tag_filepath, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        # Retirer d'éventuelles lignes blanches en fin de fichier
        while lines and lines[-1].strip() == "":
            lines.pop()
        # Si la dernière ligne correspond déjà au hashtag, on la retire temporairement
        if lines and lines[-1].strip() == tag_hashtag:
            lines.pop()
    else:
        # Création d'un fichier avec un header
        lines = [f"# {tag_clean}", "", "Liste des notes liées:"]

    # Préparer la ligne de lien pour la note (ex: "- [[Matthew Wong]]")
    note_line = f"- [[{note_link}]]"
    if note_line not in lines:
        lines.append(note_line)

    # Ajouter éventuellement une ligne vide avant le hashtag pour séparer les parties
    lines.append("")
    # Ajouter le hashtag à la fin
    lines.append(tag_hashtag)

    new_content = "\n".join(lines) + "\n"
    with open(tag_filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

def export_notes(notes):
    """Exporte les notes Anki en fichiers Markdown et met à jour les fiches de tag."""
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

        raw_html_original = note.get("fields", {}).get(anki_field_name, {}).get("value", "")
        if not raw_html_original:
            print(f"⚠️ Note {note_id} ignorée (champ '{anki_field_name}' vide ou manquant).")
            continue

        # 1. Supprimer les occlusions pour le corps ET pour le titre
        html_body_no_cloze = remove_cloze_keep_html(raw_html_original)

        # 2. Extraire le titre
        title = extract_title_from_html(html_body_no_cloze, title_max_length)

        # 3. Récupérer les tags Anki
        tags_list = note.get("tags", [])
        # S'il n'y a aucun tag, on utilise None pour signifier "Sans tag"
        if not tags_list:
            tags_list = [None]

        # 4. Contenu final du fichier (HTML + tags en bas)
        tags_md_line = "Tags: " + " ".join(f"#{tag}" for tag in tags_list if tag) if any(tags_list) else ""
        content_to_write = f"{html_body_no_cloze}\n\n---\n\n{tags_md_line}".strip()

        # 5. Création d'un hash unique pour éviter les doublons
        content_hash = hashlib.md5((html_body_no_cloze + str(note_id)).encode("utf-8")).hexdigest()
        if content_hash in seen_hashes:
            print(f"ℹ️ Note {note_id} déjà traitée (hash identique), ignorée.")
            continue
        seen_hashes.add(content_hash)

        # 6. Déterminer le nom de fichier de la note
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

        # 7. Écrire la note exportée
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

        # 8. Mettre à jour les fiches de tag
        for tag in tags_list:
            update_tag_file(tag, filename_final)

    print(f"\n✨ Exportation terminée. {exported_count} note(s) écrite(s).")

    # 9. Écrire l'index global listant les fiches de tag
    # Ajout du lien vers la note "Index"
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

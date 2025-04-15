# __init__.py
import sys
from aqt import mw
from aqt.qt import QAction
from aqt.utils import showInfo
import os, re, html, hashlib
from bs4 import BeautifulSoup
import re

# === Configuration ===
OUTPUT_DIR = os.path.expanduser("~/Downloads/Documents perso/Obsidian")
INDEX_NOTE_PATH = os.path.join(OUTPUT_DIR, "Anki.md")
ANKI_FIELD_NAME = "Texte"         # Nom du champ pour les notes "texte à trou"
TITLE_MAX_LENGTH = 95             # Longueur max du titre extrait
DECK_QUERY = "deck:*Fiches*"       # Requête pour cibler les decks
NOTE_ID_TARGET = None             # Si vous voulez cibler une note spécifique

# Pour les notes recto-verso
RECTO_VERSO_TYPES = {
    "basique (carte inversée optionnelle)",
    "basique (saisissez la réponse)",
    "généralités (deux sens)",
    "basique"
}

tag_notes_set = set()
top_level_tag_set = set()

# === Fonctions utilitaires ===

def setup_menu():
    action = QAction("Sync vers Obsidian", mw)
    # Pour mac : utilisez "Meta+O" qui correspond à Command+O,
    # pour Windows : "Ctrl+O"
    if sys.platform == "darwin":
        action.setShortcut("Meta+O")
    else:
        action.setShortcut("Ctrl+O")
    action.triggered.connect(sync_to_obsidian)
    mw.form.menuTools.addAction(action)
    print("Bouton 'Sync vers Obsidian' ajouté avec raccourci.")

def sanitize_filename(title, max_length=100):
    """Nettoie une chaîne pour l'utiliser comme nom de fichier."""
    title = title.replace("/", "-").replace(":", "-").replace("\\", "-")
    title = re.sub(r'[<>:"/\\|?*]', '', title)
    title = re.sub(r'[\x00-\x1f\x7f]', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    if not title or title.strip('.') == '':
        return "Sans titre"
    return title[:max_length].strip()

def get_field_by_name(note, field_name):
    # note._model["flds"] contient la description des champs
    # note.fields est la liste des valeurs dans l'ordre
    model = note.model()
    for index, fld in enumerate(model["flds"]):
        if fld["name"] == field_name:
            return note.fields[index]
    return ""

def extract_title_from_html(html_content, max_len):
    """Extrait la première ligne significative du HTML comme titre."""
    if not html_content:
        return "Sans titre"
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        text_content = soup.get_text(separator='\n', strip=True)
        if not text_content:
            return "Sans titre"
        # Récupération de la première ligne non vide
        for line in text_content.split('\n'):
            stripped_line = line.strip()
            if stripped_line:
                title = html.unescape(stripped_line)
                return title if len(title) <= max_len else title[:max_len] + "..."
        return "Sans titre"
    except Exception as e:
        print(f"Erreur lors de l'extraction du titre: {e}")
        return "Sans titre"

def remove_cloze_keep_html(text):
    """Supprime les marqueurs d'occlusion Anki en gardant le contenu, et remplace les &nbsp; par des espaces."""
    text = text.replace('\u00A0', ' ')
    return re.sub(r"{{c\d+::(.*?)(::.*?)?}}", r"\1", text, flags=re.DOTALL)

# === Accès aux notes via l'API Anki ===

def get_note_ids():
    """Retourne les IDs des notes correspondant à DECK_QUERY."""
    if NOTE_ID_TARGET:
        print(f"Ciblage de la note unique ID : {NOTE_ID_TARGET}")
        return [NOTE_ID_TARGET]
    print(f"Recherche des notes avec la requête '{DECK_QUERY}'...")
    note_ids = mw.col.findNotes(DECK_QUERY)
    print(f"{len(note_ids)} note(s) trouvée(s).")
    return note_ids

def get_notes_details(note_ids):
    """Retourne les objets note pour les IDs donnés."""
    notes = []
    for nid in note_ids:
        note = mw.col.getNote(nid)
        if note:
            notes.append(note)
    print(f"Détails récupérés pour {len(notes)} note(s).")
    return notes

def find_existing_file_by_id(anki_id):
    for filename in os.listdir(OUTPUT_DIR):
        if filename.endswith(".md"):
            filepath = os.path.join(OUTPUT_DIR, filename)
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()
                    if f"<!-- anki_id: {anki_id} -->" in content:
                        return filename  # On retourne le nom du fichier existant
            except Exception as e:
                print(f"Erreur lors de la lecture de {filepath} : {e}")
                continue
    return None

# === Fonction d'export vers Obsidian ===

def export_notes(notes):
    if not notes:
        print("Aucune note à exporter.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    seen_hashes = set()
    exported_count = 0

    print(f"Début de l'exportation vers : {OUTPUT_DIR}")

    for note in notes:
        nid = note.id  # Identifiant Anki de la note
        model = note.model()
        model_name = model.get("name", "").lower()

        # --- 1. Préparer les listes de tags ---
        # Garder la liste brute pour la mise à jour des fichiers de tag plus tard
        raw_tags_for_files = note.tags if hasattr(note, "tags") else []
        if not raw_tags_for_files:
            raw_tags_for_files = [None] # Pour traiter les notes sans tag si nécessaire

        # Générer les hashtags individuels pour le corps de la note Obsidian
        obsidian_tags_for_body = []
        temp_tags_list = note.tags if hasattr(note, "tags") else [] # Utiliser une liste temporaire ici
        for tag in temp_tags_list:
            if tag:
                parts = [p.strip() for p in tag.split("::") if p.strip()]
                for part in parts:
                    hashtag = f"#{part}"
                    if hashtag not in obsidian_tags_for_body:
                        obsidian_tags_for_body.append(hashtag)
        # Créer la ligne de texte pour le corps de la note (sera ajoutée plus tard)
        tags_md_line_for_body = "Tags: " + " ".join(obsidian_tags_for_body) if obsidian_tags_for_body else ""

        # --- SUPPRIMER LA PREMIÈRE BOUCLE INCORRECTE D'ICI ---

        # --- 2. Extraire le contenu et le titre ---
        content_body = ""
        title = "Sans titre" # Initialisation par défaut

        if any(fld["name"].strip().lower() == ANKI_FIELD_NAME.strip().lower() for fld in model["flds"]):
            raw_html_original = get_field_by_name(note, ANKI_FIELD_NAME)
            if not raw_html_original:
                print(f"Note {nid} ignorée (champ '{ANKI_FIELD_NAME}' vide).")
                continue
            html_body_no_cloze = remove_cloze_keep_html(raw_html_original)
            title = extract_title_from_html(html_body_no_cloze, TITLE_MAX_LENGTH)
            # Ne pas ajouter tags_md_line ici, on le fera à la fin
            content_body = html_body_no_cloze.strip()
        elif model_name in (t.lower() for t in RECTO_VERSO_TYPES):
            recto_field = note.fields[0] if note.fields else ""
            if not recto_field:
                print(f"Note {nid} ignorée (champ 'Recto' vide).")
                continue
            title = extract_title_from_html(recto_field, TITLE_MAX_LENGTH)
            verso_parts = note.fields[1:] if len(note.fields) > 1 else []
            if not verso_parts:
                print(f"Note {nid} ignorée (aucun contenu pour le verso).")
                continue
            body_html = "\n\n".join(verso_parts)
            # Ne pas ajouter tags_md_line ici
            content_body = body_html.strip()
        else:
            print(f"Note {nid} ignorée (type de carte non supporté: {model.get('name','')}).")
            continue

        # --- 3. Déterminer le nom de fichier final ---
        existing_filename = find_existing_file_by_id(nid)
        filename_final = None # Initialisation

        if existing_filename:
            filename_final = existing_filename[:-3]
        else:
            base_filename = sanitize_filename(title, max_length=TITLE_MAX_LENGTH) # Utilise le 'title' déterminé avant
            filename_final = base_filename
            suffix = 1
            while os.path.exists(os.path.join(OUTPUT_DIR, f"{filename_final}.md")):
                filename_final = f"{base_filename}_{suffix}"
                suffix += 1

        # --- 4. Préparer et écrire le contenu final de la note ---
        hidden_id_line = f"<!-- anki_id: {nid} -->"
        # Construire le contenu final ICI, en ajoutant la ligne de tags
        content_to_write = f"{hidden_id_line}\n{content_body}\n\n---\n\n{tags_md_line_for_body}".strip()

        # Vérification de hash (optionnel) - Utiliser content_to_write
        content_hash = hashlib.md5((content_to_write + str(nid)).encode("utf-8")).hexdigest()
        if content_hash in seen_hashes:
            print(f"Note {nid} déjà traitée (hash identique), ignorée.")
            continue
        seen_hashes.add(content_hash)

        # Écriture du fichier note
        filepath = os.path.join(OUTPUT_DIR, f"{filename_final}.md")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content_to_write)
            print(f"Note {nid} exportée : {filepath}")
            exported_count += 1
        except Exception as e:
            print(f"Erreur lors de l'écriture du fichier {filepath}: {e}")
            # Si l'écriture échoue, on ne veut pas traiter les tags pour cette note
            continue

        # --- 5. Mettre à jour les fichiers de tag (CORRECTEMENT PLACÉ ICI) ---
        # Utiliser la liste brute des tags originaux de la note
        for tag in raw_tags_for_files:
            if tag and "::" in tag:
                # Appeler la fonction pour les tags hiérarchiques
                update_hierarchical_tag_files(tag, filename_final)
            else:
                # Appeler la fonction pour les tags simples (ou None)
                # S'assurer que add_to_index=True est la valeur par défaut ou est spécifié
                update_tag_file(tag, filename_final, add_to_index=True)

    # --- Fin de la boucle principale 'for note in notes:' ---

    print(f"Exportation terminée : {exported_count} note(s écrite(s).")
    # La mise à jour de l'index se fait après avoir traité toutes les notes
    update_index_file()

# Ajouter le paramètre add_to_index=True par défaut
def update_tag_file(tag_name, note_link, add_to_index=True):
    tag_name = tag_name or "Sans tag"   # Si tag_name est None, le remplacer par "Sans tag"
    tag_clean = tag_name
    tag_filename = sanitize_filename(tag_clean)
    tag_filepath = os.path.join(OUTPUT_DIR, f"{tag_filename}.md")

    # Ajouter à l'ensemble pour l'index SEULEMENT si demandé
    if add_to_index:
        tag_notes_set.add(tag_filename)
        if "::" not in tag_name:
            top_level_tag_set.add(tag_filename)

    tag_hashtag = f"#{tag_clean.lower()}"

    lines = []
    if os.path.exists(tag_filepath):
        # SI LE FICHIER EXISTE : Lire son contenu
        try: # Bonne pratique d'ajouter un try/except pour la lecture
            with open(tag_filepath, "r", encoding="utf-8") as f:
                lines = f.read().splitlines() # Charger les lignes existantes
            # Optionnel: Nettoyer les lignes vides à la fin et le dernier hashtag si présent
            while lines and lines[-1].strip() == "":
                lines.pop()
            if lines and lines[-1].strip() == tag_hashtag: # Utiliser tag_hashtag défini plus bas
                lines.pop()
        except Exception as e:
            print(f"Erreur lors de la lecture du fichier tag existant {tag_filepath}: {e}")
            # Que faire en cas d'erreur de lecture ? Revenir à la valeur par défaut?
            lines = ["", "Liste des notes liées:",""] # Ou juste initialiser lines = [] ?

    else:
        # SI LE FICHIER N'EXISTE PAS : Initialiser avec l'en-tête
        lines = ["", "Liste des notes liées:",""]

    # Définir tag_hashtag ici pour qu'il soit disponible dans le 'if' ci-dessus
    tag_hashtag = f"#{tag_clean.lower()}"

    # ... (le reste de la fonction pour ajouter note_line, le hashtag final, et écrire le fichier) ...

    note_line = f"- [[{note_link}]]"
    if note_line not in lines:
        # Ajouter la ligne de note *après* le titre et l'en-tête potentiel
        if lines and lines[-1].strip().lower() == "liste des notes liées:":
             lines.append(note_line)
        elif not lines: # Cas où le fichier était vide ou erreur de lecture
             lines = ["", "Liste des notes liées:", note_line]
        else: # Ajouter à la fin si l'en-tête n'est pas là
             lines.append(note_line)

    # Assurer que le hashtag est à la fin et qu'il y a une ligne vide avant (sauf si vide)
    if lines and lines[-1].strip() != tag_hashtag:
         # Enlever le hashtag s'il est ailleurs
         lines = [l for l in lines if l.strip() != tag_hashtag]
         # Ajouter une ligne vide si nécessaire
         if lines and lines[-1].strip() != "":
             lines.append("")
         lines.append(tag_hashtag)
    elif not lines: # Si le fichier était vide
         lines = ["", "Liste des notes liées:", note_line, "", tag_hashtag]


    new_content = "\n".join(lines) + "\n"
    try:
        with open(tag_filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        print(f"Erreur lors de l'écriture du fichier tag {tag_filepath}: {e}")

def update_hierarchical_tag_files(tag_str, note_link):
    # ... (début inchangé) ...
    parts = [p.strip() for p in tag_str.split("::") if p.strip()]
    print(f"[DEBUG] Hierarchical tag parts: {parts}")
    if not parts:
        return
    if len(parts) == 1:
        # Un seul niveau = tag normal, on l'ajoute à l'index
        update_tag_file(parts[0], note_link, add_to_index=True)
    else:
        top = sanitize_filename(parts[0])
        top_level_tag_set.add(top)
        print(f"[DEBUG] Added top-level tag: {top}")
        update_parent_tag_file(parts[0], child=parts[1])
        for i in range(1, len(parts) - 1):
            update_parent_tag_file(parts[i], child=parts[i+1])
        update_tag_file(parts[-1], note_link, add_to_index=False)

def update_parent_tag_file(tag, child=None):
    """
    Met à jour la fiche d'un tag parent pour y ajouter, sous la section "Tags liés:",
    un lien vers le tag enfant. Cette fiche ne reçoit pas le lien vers la note.
    """
    tag_filename = sanitize_filename(tag)
    tag_filepath = os.path.join(OUTPUT_DIR, f"{tag_filename}.md")
    lines = []
    if os.path.exists(tag_filepath):
        with open(tag_filepath, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    else:
         lines = []
    
     # S'assurer qu'il existe une section "Tags liés:"
    # (on vérifie si on a déjà la ligne "Tags liés:" en ignorant la casse)
    if not any(line.strip().lower() == "tags liés:" for line in lines):
        lines.append("Tags liés:")

    # Si un enfant est précisé, on l'ajoute sous forme de puce
    if child:
        child_link = f"- [[{sanitize_filename(child)}]]"
        if not any(child_link in line for line in lines):
            lines.append(child_link)

    # On retire déjà l'éventuel séparateur et la ligne "Tag : ..."
    # s'ils existent pour éviter les doublons
    lines = [l for l in lines if not l.strip().startswith("---") 
                             and not l.strip().startswith("Tag : #")]

    # Ajouter le séparateur et la mention "Tag : #tag"
    lines.append("")
    lines.append("---")
    lines.append(f"Tag : #{tag.lower()}")

    # Écriture du fichier
    with open(tag_filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    tag_notes_set.add(tag_filename)

def update_tag_file_bottom(tag):
    """
    Met à jour la fiche du niveau le plus bas (child) pour afficher uniquement son hashtag.
    Cela permet de ne pas y ajouter de lien vers la note, afin que la note soit liée
    uniquement dans la fiche du parent.
    """
    tag_filename = sanitize_filename(tag)
    tag_filepath = os.path.join(OUTPUT_DIR, f"{tag_filename}.md")
    lines = []
    if os.path.exists(tag_filepath):
        with open(tag_filepath, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    else:
        lines = [f"# {tag}"]
    # Supprime les lignes commençant par "- [[" et celles contenant "Liste des fiches liées:"
    lines = [line for line in lines if not line.strip().startswith("- [[")]
    lines = [line for line in lines if "Liste des fiches liées:" not in line]
    # Assure l'affichage du hashtag à la fin
    if not any(line.strip() == f"#{tag.lower()}" for line in lines):
        lines.append("")
        lines.append(f"#{tag.lower()}")
    with open(tag_filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    tag_notes_set.add(tag_filename)

def update_tag_file_hierarchical_parent(tag, note_link, child=None):
    """
    Met à jour la fiche de tag du parent pour :
      - Ajouter une section "Liste des fiches liées:" avec le lien vers la note.
      - Ajouter une section "Tags liés:" avec le lien vers le tag enfant (si fourni).
      - Afficher en bas le hashtag du tag.
    """
    tag_filename = sanitize_filename(tag)
    tag_filepath = os.path.join(OUTPUT_DIR, f"{tag_filename}.md")
    # Si le fichier existe, on le lit ; si le fichier existe mais est vide, on l'initialise avec le titre.
    if os.path.exists(tag_filepath):
        with open(tag_filepath, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if not lines:  # Fichier existant mais vide
            lines = [f"# {tag}"]
    else:
        lines = [f"# {tag}"]
    
    # Ajoute la section "Liste des fiches liées:" si non présente
    if not any("Liste des fiches liées:" in line for line in lines):
        lines.append("")
        lines.append("Liste des fiches liées:")
    note_line = f"- [[{note_link}]]"
    if note_line not in lines:
        lines.append(note_line)
    
    # Ajoute la section "Tags liés:" et le lien vers l'enfant, si un enfant est fourni
    if child:
        if not any("Tags liés:" in line for line in lines):
            lines.append("")
            lines.append("Tags liés:")
        child_link = f"[[{sanitize_filename(child)}]]"
        if not any(child_link in line for line in lines):
            lines.append(child_link)
    
    # Ajoute le hashtag en bas, s'il n'est pas déjà présent
    if not any(line.strip() == f"#{tag.lower()}" for line in lines):
        lines.append("")
        lines.append(f"#{tag.lower()}")
    
    with open(tag_filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    tag_notes_set.add(tag_filename)

def update_parent_child_link(parent, child):
    """
    Met à jour la fiche de tag du parent pour y ajouter, sous la section "Tags liés:",
    un lien vers le tag enfant.
    """
    parent_filename = sanitize_filename(parent)
    parent_filepath = os.path.join(OUTPUT_DIR, f"{parent_filename}.md")
    lines = []
    if os.path.exists(parent_filepath):
        with open(parent_filepath, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    else:
        lines = [f"# {parent}"]
    # Ajoute la section "Tags liés:" si elle n'existe pas
    if not any("Tags liés:" in line for line in lines):
        lines.append("")
        lines.append("Tags liés:")
    child_link = f"[[{sanitize_filename(child)}]]"
    if not any(child_link in line for line in lines):
        lines.append(child_link)
    with open(parent_filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    tag_notes_set.add(parent_filename)

def update_index_file():
    index_lines = []
    if tag_notes_set:
        index_lines.append("# 📘 Index complet des fiches de tag")
        index_lines.append("")
        index_lines.append("- [[Index]]")
        index_lines.append("")
        for tag_note in sorted(tag_notes_set):
            index_lines.append(f"- [[{tag_note}]]")
    else:
        index_lines.append("Aucune fiche de tag à indexer.")
    
    try:
        with open(INDEX_NOTE_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(index_lines))
        print(f"Fichier d'index mis à jour : {INDEX_NOTE_PATH}")
    except Exception as e:
        print(f"Erreur lors de l'écriture du fichier d'index: {e}")

def clean_old_files(current_ids):
    """
    Parcourt les fichiers .md dans OUTPUT_DIR et supprime ceux dont
    le commentaire caché <!-- anki_id: X --> ne correspond pas à un ID
    présent dans current_ids (la source de vérité d'Anki).
    """
    import re
    for filename in os.listdir(OUTPUT_DIR):
        if filename.endswith(".md"):
            filepath = os.path.join(OUTPUT_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Cherche le commentaire caché contenant l'ID Anki
                match = re.search(r"<!--\s*anki_id:\s*(\d+)\s*-->", content)
                if match:
                    file_id = match.group(1)
                    if file_id not in current_ids:
                        os.remove(filepath)
                        print(f"Fichier supprimé {filepath} (ID {file_id} introuvable).")
            except Exception as e:
                print(f"Erreur lors de la vérification de {filepath} : {e}")

# === Fonction pour nettoyer les tags liés à la fiche 'Anki' mais qui ne sont liés à aucune note ===

# === Fonction pour nettoyer les tags liés à la fiche 'Anki' mais qui ne sont liés à aucune note ===

def clean_tag_files():
    """
    Parcourt les fichiers de tags et retire les lignes qui font référence à des notes supprimées.
    Supprime les fichiers de tag s'ils deviennent vides de liens (notes et tags).
    """
    # Utiliser list() pour pouvoir modifier tag_notes_set pendant l'itération si besoin
    for tag_filename in list(tag_notes_set):
        tag_filepath = os.path.join(OUTPUT_DIR, f"{tag_filename}.md")
        if os.path.exists(tag_filepath):
            try:
                with open(tag_filepath, "r", encoding="utf-8") as f:
                    # Lire les lignes ici pour éviter les problèmes avec readlines() + strip()
                    lines = f.read().splitlines()
                new_lines = []
                # Garder une trace si on trouve des liens valides
                has_valid_note_link = False
                has_tag_link = False

                for line in lines:
                    stripped = line.strip()
                    is_note_link_line = False # Flag pour savoir si c'est une ligne de lien de note

                    # Si c'est une ligne potentielle de lien de note
                    if stripped.startswith("- [["):
                        is_note_link_line = True
                        ref = re.search(r"\[\[(.*?)\]\]", stripped)
                        if ref:
                            ref_filename = ref.group(1)
                            path_to_check = os.path.join(OUTPUT_DIR, f"{ref_filename}.md")
                            # print(f"Examining line: {stripped}") # Debug
                            # print(f"Checking if file exists: {path_to_check}") # Debug
                            if os.path.exists(path_to_check):
                                new_lines.append(line) # Garder la ligne seulement si la note existe
                                has_valid_note_link = True
                            # else:
                                # print("-> File not found, removing this line.") # Debug
                        else:
                            # Lien de note mal formé? On le garde pour l'instant.
                            new_lines.append(line)
                    else:
                         # Ce n'est pas une ligne de lien de note, on la garde
                         new_lines.append(line)
                         # Vérifier si c'est un lien de tag (commence par [[ mais pas par '- [[')
                         if stripped.startswith("[[") and stripped.endswith("]]"):
                             has_tag_link = True

                # --- Début de la logique de décision (après avoir traité toutes les lignes) ---

                # Nettoyer les lignes vides potentiellement laissées à la fin
                while new_lines and not new_lines[-1].strip():
                    new_lines.pop()

                # Décider s'il faut supprimer ou garder/réécrire le fichier
                if not has_valid_note_link and not has_tag_link:
                    # Plus de liens valides (ni note, ni tag). Est-ce qu'il reste autre chose?
                    is_effectively_empty = True
                    for line in new_lines:
                        clean_line = line.strip()
                        # Si on trouve une ligne non vide qui n'est pas un titre, hashtag, ou en-tête connu
                        if clean_line and not clean_line.startswith('#') and clean_line.lower() not in ["tags liés:", "liste des notes liées:", "liste des fiches liées:"]:
                            is_effectively_empty = False
                            break

                    if is_effectively_empty:
                        try:
                            os.remove(tag_filepath)
                            print(f"Tag file {tag_filepath} deleted (no remaining links and effectively empty).")
                            # Important: Mettre à jour aussi l'ensemble pour l'index
                            if tag_filename in tag_notes_set:
                                tag_notes_set.remove(tag_filename)
                        except OSError as e:
                            print(f"Error deleting file {tag_filepath}: {e}")
                    else:
                        # Le fichier n'a pas de liens mais a d'autre contenu texte. On le garde et on le réécrit.
                        print(f"Tag file {tag_filepath} kept (no links, but other content).")
                        with open(tag_filepath, "w", encoding="utf-8") as f:
                            f.write("\n".join(new_lines) + "\n")

                else:
                    # Le fichier a des liens valides (notes ou tags), on le réécrit avec les nettoyages potentiels
                    print(f"Tag file {tag_filepath} cleaned/kept (has remaining links).")
                    with open(tag_filepath, "w", encoding="utf-8") as f:
                        f.write("\n".join(new_lines) + "\n")

            except Exception as e:
                print(f"Error cleaning tag file {tag_filepath}: {e}")
            # --- PAS DE CODE SUPPLÉMENTAIRE ICI ---
        #else: # Cas où le fichier tag listé dans tag_notes_set n'existe pas (ne devrait pas arriver)
            #print(f"Warning: Tag file {tag_filepath} listed in set but not found.")

# === Fonction appelée par le bouton ===

def sync_to_obsidian():
    note_ids = get_note_ids()
    if not note_ids:
        showInfo("Aucune note trouvée selon la requête.")
        return
    notes = get_notes_details(note_ids)
    export_notes(notes)
    # On convertit les IDs en chaînes pour la comparaison
    current_ids = set(str(nid) for nid in note_ids)
    clean_old_files(current_ids)
    clean_tag_files()
    showInfo("Export vers Obsidian terminé.")

# === Ajout du bouton dans le menu "Outils" ===

def setup_menu():
    action = QAction("Sync vers Obsidian", mw)
    action.triggered.connect(sync_to_obsidian)
    mw.form.menuTools.addAction(action)
    print("Bouton 'Sync vers Obsidian' ajouté au menu Outils.")

# Initialisation de l'addon
setup_menu()

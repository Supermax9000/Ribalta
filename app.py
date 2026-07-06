import streamlit as st
import cv2
import easyocr
import pandas as pd
import numpy as np
import re
import difflib
from datetime import datetime

# Inizializza il lettore OCR
@st.cache_resource
def load_ocr():
    return easyocr.Reader(['it', 'en'])

reader = load_ocr()

# Inizializza la tabella nella sessione
if 'database' not in st.session_state:
    st.session_state.database = pd.DataFrame(
        columns=['Data/Ora Scan', 'Codice', 'Categoria', 'Compagnia', 'Stato', 'Tipo Danno']
    )

# Memorizza il codice proposto dall'immagine per riempire la casella
if 'testo_da_inserire' not in st.session_state:
    st.session_state.testo_da_inserire = ""

# Elenco ufficiale dei prefissi ULD e delle Compagnie Aeree
PREFISSI_VALIDI = ["AKE", "AKH", "AMU", "DPE", "PAG", "PMC", "ALF", "DQP", "RMP"]

DIZIONARIO_COMPAGNIE = {
    "R7": "R7 - Contenitore Jolly / Pooling",
    "HO": "HO - Juneyao Air",
    "CA": "CA - Air China",
    "MU": "MU - China Eastern",
    "AZ": "AZ - ITA Airways",
    "LH": "LH - Lufthansa",
    "AF": "AF - Air France",
    "EK": "EK - Emirates",
    "QR": "QR - Qatar Airways",
    "XX": "XX - Sconosciuta / Altro"
}

SIGLE_COMPAGNIE = list(DIZIONARIO_COMPAGNIE.keys())

def unisci_blocchi_orizzontali(risultati_ocr, tolleranza_y=25):
    if not risultati_ocr:
        return []
    blocchi_processati = []
    
    for res in risultati_ocr:
        if isinstance(res, (list, tuple)) and len(res) >= 2:
            coordinate_quadrato = res[0]
            testo_reale = str(res[1])
            try:
                ys = [float(punto[1]) for punto in coordinate_quadrato if isinstance(punto, (list, tuple)) and len(punto) >= 2]
                xs = [float(punto[0]) for punto in coordinate_quadrato if isinstance(punto, (list, tuple)) and len(punto) >= 2]
                if ys and xs:
                    y_centro = (min(ys) + max(ys)) / 2
                    blocchi_processati.append({'y_centro': y_centro, 'x_min': min(xs), 'testo': testo_reale})
            except Exception:
                continue
        
    if not blocchi_processati:
        return []
        
    blocchi_processati.sort(key=lambda x: x['y_centro'])
    righe, riga_corrente, y_riga_corrente = [], [], -1
    
    for blocco in blocchi_processati:
        if y_riga_corrente == -1:
            y_riga_corrente = blocco['y_centro']
            riga_corrente.append(blocco)
        elif abs(blocco['y_centro'] - y_riga_corrente) <= tolleranza_y:
            riga_corrente.append(blocco)
        else:
            riga_corrente.sort(key=lambda x: x['x_min'])
            righe.append(" ".join([b['testo'] for b in riga_corrente]))
            y_riga_corrente = blocco['y_centro']
            riga_corrente = [blocco]
    if riga_corrente:
        riga_corrente.sort(key=lambda x: x['x_min'])
        righe.append(" ".join([b['testo'] for b in riga_corrente]))
    return righe

def estrai_e_pulisci_uld(lista_righe):
    for riga in lista_righe:
        riga_pulita = re.sub(r'[^A-Z0-9]', '', riga.upper())
        match_prefisso = re.search(r'^([A-Z]{3})', riga_pulita)
        if match_prefisso:
            prefisso_rilevato = match_prefisso.group(1)
            resto_riga = riga_pulita[3:]
            
            if prefisso_rilevato not in PREFISSI_VALIDI:
                corrispondenze = difflib.get_close_matches(prefisso_rilevato, PREFISSI_VALIDI, n=1, cutoff=0.3)
                prefisso_finale = corrispondenze[0] if corrispondenze else prefisso_rilevato
            else:
                prefisso_finale = prefisso_rilevato
            
            resto_corretto = resto_riga.replace('O', '0').replace('I', '1').replace('L', '1')
            numeri = re.findall(r'\d+', resto_corretto)
            
            if numeri:
                blocco_numerico = numeri[0]
                if 4 <= len(blocco_numerico) <= 5:
                    posizione_numeri = resto_corretto.find(blocco_numerico)
                    suffisso = resto_corretto[posizione_numeri + len(blocco_numerico):]
                    suffisso = re.sub(r'[^A-Z0-9]', '', suffisso)
                    
                    if not suffisso or len(suffisso) < 2:
                        if "JUNEYAO" in riga_pulita or "HO" in riga_pulita: suffisso = "HO"
                        elif "CHINA" in riga_pulita or "EASTERN" in riga_pulita: suffisso = "MU"
                        elif "R7" in riga_pulita: suffisso = "R7"
                        else: suffisso = "XX"
                        
                    return f"{prefisso_finale}{blocco_numerico}{suffisso[:2]}"
    return ""

def classifica_container(codice):
    prefisso = codice[:3]
    dizionario_categorie = {
        "AKE": "📦 Container Standard (Dolly)",
        "AKH": "✈️ Container Basso (A320/A321)",
        "AMU": "🐋 Container Grande (Main Deck)",
        "DPE": "📦 Container Profilato Standard (LD3)",
        "PAG": "🏁 Pallet per Merci Pallettizzate",
        "PMC": "📐 Pallet Grande Standard"
    }
    return dizionario_categorie.get(prefisso, "❓ Altro / Non Specificato")
st.title("🧳 Gestione Rapida Contenitori ULD")
st.write("Controlla il codice e premi **INVIO** dentro la casella per confermare il salvataggio.")

# Sezione Opzionale dello Scanner Ottico
with st.expander("📷 Usa Fotocamera o Carica Foto per estrarre il codice"):
    modalita = st.radio("Sorgente immagine:", ["Carica file immagine (JPG/PNG)", "Usa Fotocamera Smartphone"])
    img_file = st.file_uploader("Scegli un file immagine", type=["jpg", "jpeg", "png"]) if modalita == "Carica file immagine (JPG/PNG)" else st.camera_input("Scatta una foto")

    if img_file is not None:
        file_bytes = np.asarray(bytearray(img_file.read()), dtype=np.uint8)
        opencv_img = cv2.imdecode(file_bytes, 1)
        st.image(opencv_img, channels="BGR", caption="Anteprima", use_container_width=True)
        
        with st.spinner("Lettura ottica del testo..."):
            risultati_ocr = reader.readtext(opencv_img)
        
        codice_da_ocr = estrai_e_pulisci_uld(unisci_blocchi_orizzontali(risultati_ocr)) if risultati_ocr else ""
        if codice_da_ocr:
            # Inietta il testo estratto direttamente nella variabile di stato
            st.session_state.testo_da_inserire = codice_da_ocr
            st.success(f"Codice estratto: **{codice_da_ocr}**. Clicca sulla casella sotto e premi INVIO per salvare.")
        else:
            st.warning("Impossibile isolare un codice dall'immagine.")

st.markdown("---")
st.subheader("📝 Inserimento Diretto")

col_stato1, col_stato2 = st.columns(2)
with col_stato1:
    is_danneggiato = st.checkbox("Segnala come DANNEGGIATO", key='check_danno')
with col_stato2:
    tipo_danno = st.text_input("Note Danno (opzionale):", key='nota_danno', disabled=not is_danneggiato)

# 🟢 LOGICA DI SALVATAGGIO REATTIVA FLUIDA (Risolve il blocco dell'Invio)
codice_input = st.text_input(
    "Controlla il codice e premi INVIO sulla tastiera per confermare:", 
    value=st.session_state.testo_da_inserire,
    placeholder="Es: AKE12345AZ"
).upper().strip()

# Se l'utente preme INVIO su una casella piena e NON è un inserimento duplicato istantaneo di loop
if codice_input and codice_input != st.session_state.get('ultimo_salvato', ''):
    sigla_rilevata = codice_input[-2:] if len(codice_input) >= 5 else "XX"
    if sigla_rilevata not in SIGLE_COMPAGNIE:
        sigla_rilevata = "XX"
        
    if len(codice_input) >= 5 and sigla_rilevata != "XX":
        codice_salvataggio = codice_input[:-2] + sigla_rilevata
        nome_compagnia = DIZIONARIO_COMPAGNIE[sigla_rilevata]
    else:
        codice_salvataggio = codice_input
        nome_compagnia = DIZIONARIO_COMPAGNIE["XX"]
        
    categoria = classifica_container(codice_salvataggio)
    stato_container = "❌ Danneggiato" if is_danneggiato else "✅ Integro"
    testo_danno = tipo_danno if is_danneggiato else "-"

    if codice_salvataggio in st.session_state.database['Codice'].values:
        st.error(f"🚨 Il contenitore **{codice_salvataggio}** è già registrato!")
    else:
        ora_attuale = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        nuovo_record = pd.DataFrame([{
            'Data/Ora Scan': ora_attuale,
            'Codice': codice_salvataggio, 
            'Categoria': categoria, 
            'Compagnia': nome_compagnia,
            'Stato': stato_container,
            'Tipo Danno': testo_danno
        }])
        st.session_state.database = pd.concat([st.session_state.database, nuovo_record], ignore_index=True)
        st.toast(f"💾 {codice_salvataggio} aggiunto correttamente!")
        
        # Svuota il campo di testo e memorizza l'ultimo salvato per bloccare i loop di rinfresco
        st.session_state.ultimo_salvato = codice_input
        st.session_state.testo_da_inserire = ""
        st.rerun()

st.markdown("---")
st.subheader("📋 Inventario Modificabile e Ordinato")

if not st.session_state.database.empty:
    tabella_modificata = st.data_editor(
        st.session_state.database,
        use_container_width=True,
        num_rows="dynamic"
    )
    
    if not tabella_modificata.equals(st.session_state.database):
        st.session_state.database = tabella_modificata
        st.rerun()
    
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        csv = st.session_state.database.to_csv(index=False).encode('utf-8')
        st.download_button(label="📥 Scarica Excel/CSV", data=csv, file_name='inventario_uld_completo.csv', mime='text/csv', use_container_width=True)
    with col_dl2:
        testo_report = "--- REPORT INVENTARIO CONTAINER ULD ---\n"
        testo_report += f"Generato il: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        testo_report += f"Totale elementi: {len(st.session_state.database)}\n---------------------------------------\n\n"
        for _, row in st.session_state.database.iterrows():
            testo_report += f"[{row['Data/Ora Scan']}] - {row['Codice']} ({row['Compagnia']})\n ↳ Tipo: {row['Categoria']}\n ↳ Stato: {row['Stato']} | Note: {row['Tipo Danno']}\n---------------------------------------\n"
        st.download_button(label="📄 Scarica Report TXT", data=testo_report, file_name='inventario_uld_completo.txt', mime='text/plain', use_container_width=True)
else:
    st.info("Nessun dato in memoria. Inserisci un codice o scansiona per iniziare.")

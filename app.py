import streamlit as st

# Fondamentale: deve essere il primissimo comando in assoluto all'inizio del file
st.set_page_config(
    page_title="Scanner ULD",
    page_icon="🧳",
    layout="wide",
    initial_sidebar_state="collapsed"
)

import cv2
import easyocr
import pandas as pd
import numpy as np
import re
import difflib
import os
import zoneinfo
from datetime import datetime

# Nome del file fisico dove verranno memorizzati i dati sul server cloud
FILE_DATABASE = "inventario_permanente.csv"

# Inizializza il lettore OCR
@st.cache_resource
def load_ocr():
    return easyocr.Reader(['it', 'en'])

reader = load_ocr()

# FUNZIONE DI CARICAMENTO: Legge il file CSV permanente se esiste, altrimenti ne crea uno vuoto
def carica_database_permanente():
    column_order = ['Stato', 'Compagnia', 'Codice', 'Categoria', 'Data/Ora Scan', 'Tipo Danno']
    if os.path.exists(FILE_DATABASE):
        try:
            df = pd.read_csv(FILE_DATABASE)
            if not df.empty and 'Stato' in df.columns:
                df['Stato'] = df['Stato'].apply(lambda x: "❌" if "Danneggiato" in str(x) or "❌" in str(x) else "✅")
            for col in column_order:
                if col not in df.columns:
                    df[col] = "-"
            return df[column_order]
        except Exception:
            pass
    return pd.DataFrame(columns=column_order)

# Inizializza la tabella nella sessione prelevando i dati dal file permanente
if 'database' not in st.session_state:
    st.session_state.database = carica_database_permanente()

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

def chiave_ordinamento_naturale(testo):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(testo))]

# 🟢 FUNZIONE CORRETTA: Rimossa la sintassi errata alla riga 89 dividendo l'assegnazione
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
def al_pressione_invio():
    codice_grezzo = st.session_state.campo_input_interattivo.upper().strip()
    if not codice_grezzo:
        return
        
    sigla_rilevata = codice_grezzo[-2:] if len(codice_grezzo) >= 5 else "XX"
    if sigla_rilevata not in SIGLE_COMPAGNIE:
        sigla_rilevata = "XX"
        
    if len(codice_grezzo) >= 5 and sigla_rilevata != "XX":
        codice_salvataggio = codice_grezzo[:-2] + sigla_rilevata
        nome_compagnia = DIZIONARIO_COMPAGNIE[sigla_rilevata]
    else:
        codice_salvataggio = codice_grezzo
        nome_compagnia = DIZIONARIO_COMPAGNIE["XX"]
        
    categoria = classifica_container(codice_salvataggio)
    stato_container = "❌" if st.session_state.get('check_danno', False) else "✅"
    testo_danno = st.session_state.get('nota_danno', "") if st.session_state.get('check_danno', False) else "-"
    if not testo_danno: 
        testo_danno = "-"

    if codice_salvataggio in st.session_state.database['Codice'].values:
        st.session_state.messaggio_errore = f"🚨 Il contenitore **{codice_salvataggio}** è già registrato!"
    else:
        if 'messaggio_errore' in st.session_state:
            del st.session_state.messaggio_errore
            
        fuso_orario_italia = zoneinfo.ZoneInfo("Europe/Rome")
        ora_attuale = datetime.now(fuso_orario_italia).strftime("%Y-%m-%d %H:%M:%S")
        
        nuovo_record = pd.DataFrame([{
            'Stato': stato_container,
            'Compagnia': nome_compagnia,
            'Codice': codice_salvataggio, 
            'Categoria': categoria, 
            'Data/Ora Scan': ora_attuale,
            'Tipo Danno': testo_danno
        }])
        
        st.session_state.database = pd.concat([st.session_state.database, nuovo_record], ignore_index=True)
        st.session_state.database.to_csv(FILE_DATABASE, index=False)
        st.toast(f"💾 {codice_salvataggio} salvato permanentemente!")
        
    st.session_state.campo_input_interattivo = ""

st.title("🧳 Gestione Rapida Contenitori ULD")
st.write("I dati sono salvati in automatico con l'orario ufficiale italiano (Roma).")

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
            st.session_state.campo_input_interattivo = codice_da_ocr
            st.success(f"Codice estratto: **{codice_da_ocr}**. Controllalo sotto e premi INVIO per confermare.")
        else:
            st.warning("Impossibile isolare un codice dall'immagine.")

st.markdown("---")
st.subheader("📝 Inserimento Diretto")

col_stato1, col_stato2 = st.columns(2)
with col_stato1:
    is_danneggiato = st.checkbox("Segnala come DANNEGGIATO", key='check_danno')
with col_stato2:
    tipo_danno = st.text_input("Note Danno (opzionale):", key='nota_danno', disabled=not is_danneggiato)

if 'messaggio_errore' in st.session_state:
    st.error(st.session_state.messaggio_errore)
    del st.session_state.messaggio_errore

st.text_input(
    "Controlla il codice e premi INVIO sulla tastiera per confermare:", 
    key="campo_input_interattivo",
    placeholder="Es: AKE12345AZ",
    on_change=al_pressione_invio
)

st.markdown("---")
st.subheader("📋 Inventario Modificabile e Ordinato")
st.caption("💡 L'ordinamento definitivo applicato è: Compagnia ➔ Categoria ➔ Codice (Ordinamento Naturale).")

if not st.session_state.database.empty:
    if st.button("🗑️ Svuota Tutto l'Inventario", help="Cancella definitivamente tutti i record salvati"):
        st.session_state.database = pd.DataFrame(columns=['Stato', 'Compagnia', 'Codice', 'Categoria', 'Data/Ora Scan', 'Tipo Danno'])
        st.session_state.database.to_csv(FILE_DATABASE, index=False)
        st.rerun()

if not st.session_state.database.empty:
    df_da_ordinare = st.session_state.database.copy()
    df_da_ordinare['chiave_codice'] = df_da_ordinare['Codice'].apply(chiave_ordinamento_naturale)
    
    df_ordinato = df_da_ordinare.sort_values(
        by=['Compagnia', 'Categoria', 'chiave_codice'], 
        key=lambda x: x if x.name != 'chiave_codice' else None
    ).reset_index(drop=True)
    
    df_ordinato = df_ordinato[['Stato', 'Compagnia', 'Codice', 'Categoria', 'Data/Ora Scan', 'Tipo Danno']]
    
    tabella_modificata = st.data_editor(
        df_ordinato,
        use_container_width=True,
        num_rows="dynamic"
    )
    
    if not tabella_modificata.equals(df_ordinato):
        st.session_state.database = tabella_modificata
        st.session_state.database.to_csv(FILE_DATABASE, index=False)
        st.rerun()
    
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        csv = st.session_state.database.to_csv(index=False).encode('utf-8')
        st.download_button(label="📥 Scarica Excel/CSV", data=csv, file_name='inventario_uld_completo.csv', mime='text/csv', use_container_width=True)
    with col_dl2:
        fuso_orario_italia = zoneinfo.ZoneInfo("Europe/Rome")
        testo_report = "--- REPORT INVENTARIO CONTAINER ULD ---\n"
        testo_report += f"Generato il: {datetime.now(fuso_orario_italia).strftime('%Y-%m-%d %H:%M:%S')}\n"
        testo_report += f"Totale elementi: {len(st.session_state.database)}\n---------------------------------------\n\n"
        for _, row in st.session_state.database.iterrows():
            testo_report += f"[{row['Data/Ora Scan']}] {row['Stato']} - {row['Codice']} ({row['Compagnia']})\n ↳ Tipo: {row['Categoria']} | Note: {row['Tipo Danno']}\n---------------------------------------\n"
        st.download_button(label="📄 Scarica Report TXT", data=testo_report, file_name='inventario_uld_completo.txt', mime='text/plain', use_container_width=True)
else:
    st.info("Nessun dato in memoria. Inserisci un codice o scansiona per iniziare.")

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import qrcode
from io import BytesIO
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="MK Deluxe X Rater", page_icon="🏎️", layout="centered")

# --- 2. INITIALISATION FIREBASE ---
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        # Récupère les credentials depuis les st.secrets (configurés dans l'étape 4 du guide)
        cred_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = init_firebase()

# --- 3. GESTION DES PARAMETRES D'URL (Pour rejoindre via QR Code) ---
query_params = st.query_params
session_id_from_url = query_params.get("session", None)

# --- 4. FONCTIONS DE LA BASE DE DONNEES ---
def get_all_tracks():
    tracks_ref = db.collection('tracks').stream()
    # Trie par ordre alphabétique
    return sorted([track.id for track in tracks_ref])

def create_session(mc_name):
    import uuid
    new_session_id = str(uuid.uuid4())[:8] # Un ID court de 8 caractères
    db.collection('sessions').document(new_session_id).set({
        'mc': mc_name,
        'current_track': 'Waiting for MC to choose...',
        'active': True
    })
    return new_session_id

def update_current_track(session_id, track_name):
    db.collection('sessions').document(session_id).update({
        'current_track': track_name
    })

def submit_rating(session_id, player_name, track_name, creativity, difficulty, driving):
    doc_id = f"{track_name}_{player_name}"
    db.collection('sessions').document(session_id).collection('ratings').document(doc_id).set({
        'player': player_name,
        'track': track_name,
        'creativity': creativity,
        'difficulty': difficulty,
        'driving': driving,
        'total': creativity + difficulty + driving
    })
    st.success(f"Rating saved for {track_name}!")

# --- 5. INTERFACE UTILISATEUR ---
st.title("🏎️ MK Deluxe X - Rater")

# Si on n'a pas de session en cours (Accueil)
if not session_id_from_url:
    st.write("### Welcome! Are you the Master of Ceremony?")
    mc_name = st.text_input("Enter your name (MC):")
    
    if st.button("Create New Session"):
        if mc_name:
            new_id = create_session(mc_name)
            st.session_state['session_id'] = new_id
            st.session_state['is_mc'] = True
            st.query_params["session"] = new_id
            st.rerun()
        else:
            st.warning("Please enter your name.")
            
else:
    # Nous sommes DANS une session
    session_id = session_id_from_url
    is_mc = st.session_state.get('is_mc', False)
    
    # Auto-refresh pour que les joueurs voient les changements du MC (toutes les 3 secondes)
    if not is_mc:
        st_autorefresh(interval=3000, key="datarefresh")

    # Récupérer les infos de la session
    session_doc = db.collection('sessions').document(session_id).get()
    if not session_doc.exists:
        st.error("Session not found!")
        st.stop()
        
    session_data = session_doc.to_dict()
    current_track = session_data.get('current_track', 'Waiting...')

    st.write(f"**Session ID:** `{session_id}` | **MC:** {session_data['mc']}")
    st.markdown("---")

    # --- INTERFACE DU MAITRE DE CEREMONIE ---
    if is_mc:
        st.subheader("👑 Master of Ceremony Control")
        
        # Générer et afficher le QR Code
        # On construit l'URL de base (Streamlit Cloud URL)
        # /!\ ATTENTION: En développement local, ce sera localhost. En prod, remplace par ton URL Streamlit.
        # Streamlit n'a pas de moyen natif de connaître sa propre URL publique de manière 100% fiable, 
        # donc on demande au MC de la confirmer ou on met un text input.
        base_url = "https://TON_APP_NAME.streamlit.app" # <--- METS TON URL ICI PLUS TARD
        if "localhost" in st.query_params: # Petit hack pour dev local
            base_url = "http://localhost:8501"
            
        join_url = f"{base_url}/?session={session_id}"
        
        qr = qrcode.QRCode(box_size=5, border=2)
        qr.add_data(join_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buf = BytesIO()
        img.save(buf, format="PNG")
        
        col1, col2 = st.columns([1, 2])
        with col1:
            st.image(buf.getvalue(), caption="Scan to join!")
        with col2:
            st.write("Share this link with players:")
            st.code(join_url)

        st.markdown("---")
        st.subheader("🏁 Select Track to Play")
        tracks = get_all_tracks()
        
        if not tracks:
            st.warning("No tracks found in Firebase! Did you run upload_tracks.py?")
        else:
            selected_track = st.selectbox("Choose a track", tracks)
            if st.button("Set Current Track & Broadcast", type="primary"):
                update_current_track(session_id, selected_track)
                st.success(f"Track updated to {selected_track}!")
                st.rerun()

    # --- INTERFACE DES JOUEURS (ET DU MC POUR VOTER) ---
    st.subheader(f"🍄 Current Track: **{current_track}**")
    
    if current_track != 'Waiting for MC to choose...':
        with st.form("rating_form"):
            player_name = st.text_input("Your Name:", value=session_data['mc'] if is_mc else "")
            
            st.write("Rate this track (1 = Bad, 10 = Masterpiece)")
            creativity = st.slider("Creativity (Design, Visuals, Ideas)", 1, 10, 5)
            difficulty = st.slider("Difficulty", 1, 10, 5)
            driving = st.slider("Driving (Pilotage, Fun to drive, Flow)", 1, 10, 5)
            
            submit = st.form_submit_button("Submit Rating 🏎️")
            
            if submit:
                if player_name:
                    submit_rating(session_id, player_name, current_track, creativity, difficulty, driving)
                else:
                    st.error("Please enter your name!")
                    
        # Afficher les scores actuels pour ce circuit
        st.markdown("### 🏆 Ratings so far")
        ratings_ref = db.collection('sessions').document(session_id).collection('ratings').where('track', '==', current_track).stream()
        
        for r in ratings_ref:
            data = r.to_dict()
            st.write(f"**{data['player']}**: Total {data['total']}/30 (Cr: {data['creativity']}, Dif: {data['difficulty']}, Pil: {data['driving']})")

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import qrcode
from io import BytesIO
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import altair as alt

# --- 1. CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="MK Deluxe X Rater", page_icon="🏎️", layout="centered")

# --- 2. INITIALISATION FIREBASE ---
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        # Récupère les credentials depuis les st.secrets
        cred_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = init_firebase()

# --- 3. GESTION DES PARAMETRES D'URL ---
query_params = st.query_params
session_id_from_url = query_params.get("session", None)

# --- 4. FONCTIONS DE LA BASE DE DONNEES ---
@st.cache_data(ttl=600)
def get_all_tracks_data():
    # Récupère toutes les données (Track, Author, Details)
    tracks_ref = db.collection('tracks').stream()
    return [track.to_dict() for track in tracks_ref]

def get_all_ratings():
    # collection_group permet de récupérer toutes les notes de toutes les sessions confondues !
    ratings_ref = db.collection_group('ratings').stream()
    return [r.to_dict() for r in ratings_ref]

def create_session(mc_name):
    import uuid
    new_session_id = str(uuid.uuid4())[:8]
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

def submit_rating(session_id, player_name, track_name, creativity, combativity, driving):
    doc_id = f"{track_name}_{player_name}"
    db.collection('sessions').document(session_id).collection('ratings').document(doc_id).set({
        'session_id': session_id,
        'player': player_name,
        'track': track_name,
        'creativity': creativity,
        'combativity': combativity,
        'driving': driving,
        'total': creativity + combativity + driving
    })
    st.success(f"Rating saved for {track_name}!")

# --- 5. INTERFACE UTILISATEUR ---
st.title("🏎️ MK Deluxe X - Rater")

# Création de deux onglets principaux
tab_play, tab_stats = st.tabs(["🎮 Play & Rate", "📊 Statistics"])

# ==========================================
# ONGLET 1 : JEU ET NOTATION
# ==========================================
with tab_play:
    # Si on n'a pas de session en cours (Accueil)
    if not session_id_from_url:
        st.write("### Welcome! Are you the Master of Ceremony?")
        mc_name = st.text_input("Enter your name (MC):")
        
        if st.button("Create New Session", type="primary"):
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
        
        # Auto-refresh pour les joueurs
        if not is_mc:
            st_autorefresh(interval=3000, key="datarefresh")

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
            
            # Affichage QR Code
            base_url = "https://mk-rating-app.streamlit.app"
            if "localhost" in st.query_params:
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
            
            tracks_data = get_all_tracks_data()
            all_ratings = get_all_ratings()
            
            if not tracks_data:
                st.warning("No tracks found in Firebase!")
            else:
                # --- Filtres ---
                col_filt1, col_filt2 = st.columns(2)
                
                with col_filt1:
                    # Extraire les 'Details' uniques pour le filtre
                    details_set = set(t.get('Details', '') for t in tracks_data if t.get('Details'))
                    details_list = sorted(list(details_set))
                    selected_detail = st.selectbox("Filter by Details:", ["All"] + details_list)
                    
                with col_filt2:
                    st.write("") # Espacement
                    st.write("") 
                    hide_rated = st.checkbox("Hide already rated tracks")

                # Appliquer les filtres
                rated_track_names = set(r.get('track', '') for r in all_ratings)
                
                filtered_tracks = []
                for t in tracks_data:
                    track_name = t.get('Track', t.get('name', 'Unknown'))
                    
                    # Filtre Details
                    if selected_detail != "All" and t.get('Details', '') != selected_detail:
                        continue
                        
                    # Filtre Déjà noté
                    if hide_rated and track_name in rated_track_names:
                        continue
                        
                    filtered_tracks.append(track_name)
                
                filtered_tracks.sort()

                if not filtered_tracks:
                    st.info("No tracks match your current filters.")
                else:
                    selected_track = st.selectbox("Choose a track (Type on your keyboard to search 🔍):", filtered_tracks)
                    
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
                combativity = st.slider("Combativity (Brawling, Items, CPU)", 1, 10, 5)
                driving = st.slider("Driving (Pilotage, Fun to drive, Flow)", 1, 10, 5)
                
                submit = st.form_submit_button("Submit Rating 🏎️")
                
                if submit:
                    if player_name:
                        submit_rating(session_id, player_name, current_track, creativity, combativity, driving)
                    else:
                        st.error("Please enter your name!")
                        
            # Afficher les scores actuels pour ce circuit
            st.markdown("### 🏆 Ratings for this track")
            ratings_ref = db.collection('sessions').document(session_id).collection('ratings').where('track', '==', current_track).stream()
            
            for r in ratings_ref:
                data = r.to_dict()
                st.write(f"**{data['player']}**: Total {data['total']}/30 (Cr: {data['creativity']}, Comb: {data['combativity']}, Driv: {data['driving']})")

# ==========================================
# ONGLET 2 : STATISTIQUES GLOBALES
# ==========================================
with tab_stats:
    st.header("📊 Global Track Rankings")
    st.write("Click on any column header to sort the table.")
    
    all_global_ratings = get_all_ratings()
    
    if not all_global_ratings:
        st.info("No ratings have been submitted yet. Start playing!")
    else:
        # Création du DataFrame Pandas
        df = pd.DataFrame(all_global_ratings)
        
        # Grouper par circuit et calculer la moyenne
        stats_df = df.groupby('track').agg(
            Votes=('player', 'count'),
            Creativity=('creativity', 'mean'),
            Combativity=('combativity', 'mean'),
            Driving=('driving', 'mean'),
            Total=('total', 'mean')
        ).reset_index()
        
        # Renommer la colonne track pour l'affichage
        stats_df = stats_df.rename(columns={'track': 'Track Name'})
        
        # Configuration des colonnes optimisée pour le format Mobile (noms courts et emojis)
        st.dataframe(
            stats_df,
            column_config={
                "Track Name": st.column_config.TextColumn("Track", width="medium"),
                "Votes": st.column_config.NumberColumn("🗳️", help="Number of ratings"),
                "Creativity": st.column_config.ProgressColumn(
                    "🎨 Creat.",
                    help="Average Creativity Rating",
                    format="%.2f",
                    min_value=0,
                    max_value=10,
                ),
                "Combativity": st.column_config.ProgressColumn(
                    "🥊 Comb.",
                    help="Average Combativity Rating",
                    format="%.2f",
                    min_value=0,
                    max_value=10,
                ),
                "Driving": st.column_config.ProgressColumn(
                    "🏎️ Driv.",
                    help="Average Driving Rating",
                    format="%.2f",
                    min_value=0,
                    max_value=10,
                ),
                "Total": st.column_config.ProgressColumn(
                    "⭐ Total",
                    help="Average Total Score",
                    format="%.2f",
                    min_value=0,
                    max_value=30,
                ),
            },
            hide_index=True,
            use_container_width=True
        )

        # --- NOUVEAU : TABLEAU DE DISTRIBUTION DES NOTES (HEATMAP) ---
        st.markdown("---")
        st.subheader("📈 Score Distribution Heatmap")
        st.write("Number of times each score (10 to 1) was given for each criterion.")
        
        # Initialisation de la structure de données pour Altair
        dist_data = []
        scores_list = list(range(10, 0, -1)) # Liste décroissante de 10 à 1
        
        # On boucle sur nos 3 critères principaux
        for col_id, col_label in [("creativity", "🎨 Creativity"), ("combativity", "🥊 Combativity"), ("driving", "🏎️ Driving")]:
            counts = df[col_id].value_counts()
            for score in scores_list:
                dist_data.append({
                    "Criterion": col_label,
                    "Score Given": str(score), # En string pour que l'axe soit discret et non continu
                    "Number of Votes": int(counts.get(score, 0))
                })
                
        heatmap_df = pd.DataFrame(dist_data)
        
        # Création de la Heatmap avec Altair
        base = alt.Chart(heatmap_df).encode(
            x=alt.X('Score Given:O', sort=[str(s) for s in scores_list], axis=alt.Axis(labelAngle=0)),
            y=alt.Y('Criterion:N', title=None, sort=None),
        )

        # Génération des blocs de couleur (nuances de bleu)
        heatmap = base.mark_rect().encode(
            color=alt.Color('Number of Votes:Q', scale=alt.Scale(scheme='blues'), legend=alt.Legend(title="Votes"))
        )

        # Ajout du chiffre exact par dessus la couleur (noir ou blanc selon le fond)
        text = base.mark_text(baseline='middle').encode(
            text='Number of Votes:Q',
            color=alt.condition(
                alt.datum['Number of Votes'] > heatmap_df['Number of Votes'].max() / 2,
                alt.value('white'),
                alt.value('black')
            )
        )

        # Affichage du graphique
        chart = (heatmap + text).properties(height=250)
        st.altair_chart(chart, use_container_width=True)

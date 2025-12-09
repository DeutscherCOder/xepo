from flask import Flask, render_template, request, send_file, after_this_request, jsonify
import os
import shutil
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
import uuid
import concurrent.futures
import time

app = Flask(__name__)

# Pfade setzen
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, 'downloads')

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

def get_spotify_client(c_id, c_secret):
    try:
        auth_manager = SpotifyClientCredentials(client_id=c_id, client_secret=c_secret)
        return spotipy.Spotify(auth_manager=auth_manager)
    except:
        return None

def download_engine(info):
    """Die optimierte Download-Logik mit Anti-Bot"""
    query = info['query']
    folder = info['folder']
    quality = info.get('quality', '192')
    
    # ANTI-BOT CONFIGURATION
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{folder}/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': quality,
        }],
        # WICHTIG: Tarnung als Android Client umgeht oft die Login-Sperre
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch',
        'noplaylist': True,
        'nocheckcertificate': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([query])
    except Exception as e:
        print(f"❌ Fehler bei {query}: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_info', methods=['POST'])
def get_info():
    data = request.json
    link = data.get('link')
    c_id = data.get('cid')
    c_secret = data.get('cs')

    if not c_id or not c_secret:
        return jsonify({'error': 'Bitte API Keys in den Einstellungen eintragen!'}), 401

    sp = get_spotify_client(c_id, c_secret)
    if not sp:
        return jsonify({'error': 'API Keys sind ungültig.'}), 401

    try:
        if "track" in link:
            track = sp.track(link)
            return jsonify({
                'type': 'track',
                'name': track['name'],
                'artist': track['artists'][0]['name'],
                'image': track['album']['images'][0]['url']
            })
        elif "playlist" in link:
            pl = sp.playlist(link)
            return jsonify({
                'type': 'playlist',
                'name': pl['name'],
                'count': pl['tracks']['total'],
                'image': pl['images'][0]['url']
            })
    except Exception as e:
        return jsonify({'error': 'Spotify Link ungültig oder API Limit erreicht.'}), 400

@app.route('/download', methods=['POST'])
def download():
    link = request.form.get('link')
    quality = request.form.get('quality', '192')
    custom_name = request.form.get('custom_name') # Neuer Custom Name
    force_zip = request.form.get('force_zip') # Checkbox
    
    c_id = request.form.get('cid')
    c_secret = request.form.get('cs')

    sp = get_spotify_client(c_id, c_secret)
    if not sp:
        return "Error: API Keys fehlen."

    # Session erstellen
    session_id = str(uuid.uuid4())
    session_folder = os.path.join(DOWNLOAD_FOLDER, session_id)
    os.makedirs(session_folder)

    try:
        final_file_path = ""
        download_filename = ""
        tasks = []
        is_playlist = False
        default_name = "music"

        # --- METADATA HOLEN ---
        if "track" in link:
            track = sp.track(link)
            query = f"{track['artists'][0]['name']} - {track['name']} audio"
            tasks.append({'query': query, 'folder': session_folder, 'quality': quality})
            default_name = f"{track['artists'][0]['name']} - {track['name']}"
            
        elif "playlist" in link:
            is_playlist = True
            results = sp.playlist_tracks(link)
            pl_data = sp.playlist(link)
            default_name = pl_data['name']
            
            for item in results['items']:
                if item['track']:
                    query = f"{item['track']['artists'][0]['name']} - {item['track']['name']} audio"
                    tasks.append({'query': query, 'folder': session_folder, 'quality': quality})

        # --- DOWNLOAD STARTEN (Parallel) ---
        # Wir reduzieren auf 4 Workers, um YouTube nicht zu triggern
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            executor.map(download_engine, tasks)

        # Überprüfen, ob Dateien da sind
        files = os.listdir(session_folder)
        if not files:
            raise Exception("Keine Songs konnten heruntergeladen werden (YouTube Block).")

        # --- NAMEN SETZEN ---
        if custom_name and custom_name.strip() != "":
            download_filename = custom_name.strip()
        else:
            download_filename = default_name

        # --- ZIP ODER FILE ---
        # Wenn Playlist ODER "Force ZIP" an ist -> ZIPPEN
        if is_playlist or force_zip == "true" or len(files) > 1:
            shutil.make_archive(os.path.join(DOWNLOAD_FOLDER, session_id), 'zip', session_folder)
            final_file_path = os.path.join(DOWNLOAD_FOLDER, session_id + '.zip')
            
            if not download_filename.endswith('.zip'):
                download_filename += ".zip"
        
        else:
            # Einzelne MP3
            final_file_path = os.path.join(session_folder, files[0])
            download_filename = files[0] # Original Dateiname behalten oder umbenennen
            if custom_name:
                download_filename = custom_name + ".mp3"

        # --- CLEANUP & SEND ---
        @after_this_request
        def cleanup(response):
            try:
                # Ordner löschen
                if os.path.exists(session_folder): shutil.rmtree(session_folder)
                # Zip File löschen (falls zip erstellt wurde)
                if os.path.exists(final_file_path) and final_file_path.startswith(DOWNLOAD_FOLDER):
                    os.remove(final_file_path)
            except Exception as e:
                print(f"Cleanup Error: {e}")
            return response

        return send_file(final_file_path, as_attachment=True, download_name=download_filename)

    except Exception as e:
        # Aufräumen bei Fehler
        if os.path.exists(session_folder): shutil.rmtree(session_folder)
        return f"<h1>Download Fehlgeschlagen</h1><p>{str(e)}</p><br><p>Möglicher Grund: YouTube blockiert Render Server IP. Versuche es lokal.</p>"

if __name__ == '__main__':
    app.run(debug=True, port=5000)

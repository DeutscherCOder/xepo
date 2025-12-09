from flask import Flask, render_template, request, send_file, after_this_request, jsonify
import os
import shutil
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
import uuid
import concurrent.futures

app = Flask(__name__)

# Keine globalen Keys mehr!
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, 'downloads')

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

def get_spotify_client(c_id, c_secret):
    """Erstellt eine temporäre Spotify-Verbindung mit User-Keys"""
    try:
        auth_manager = SpotifyClientCredentials(client_id=c_id, client_secret=c_secret)
        return spotipy.Spotify(auth_manager=auth_manager)
    except:
        return None

def download_engine(info):
    """Die Download Logik"""
    query = info['query']
    folder = info['folder']
    quality = info.get('quality', '192')
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{folder}/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': quality,
        }],
        'concurrent_fragment_downloads': 4,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch',
        'noplaylist': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([query])
    except Exception as e:
        print(f"Error downloading {query}: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_info', methods=['POST'])
def get_info():
    data = request.json
    link = data.get('link')
    c_id = data.get('cid')     # User Key
    c_secret = data.get('cs')  # User Secret

    if not c_id or not c_secret:
        return jsonify({'error': 'Missing API Keys'}), 401

    sp = get_spotify_client(c_id, c_secret)
    if not sp:
        return jsonify({'error': 'Invalid API Keys'}), 401

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
        return jsonify({'error': str(e)}), 400

@app.route('/download', methods=['POST'])
def download():
    link = request.form.get('link')
    quality = request.form.get('quality', '192')
    c_id = request.form.get('cid')
    c_secret = request.form.get('cs')

    sp = get_spotify_client(c_id, c_secret)
    if not sp:
        return "Error: Invalid or Missing API Keys. Please check settings."

    session_id = str(uuid.uuid4())
    session_folder = os.path.join(DOWNLOAD_FOLDER, session_id)
    os.makedirs(session_folder)

    try:
        download_path = ""
        filename = ""
        tasks = []

        if "track" in link:
            track = sp.track(link)
            query = f"{track['artists'][0]['name']} - {track['name']} audio"
            tasks.append({'query': query, 'folder': session_folder, 'quality': quality})
            filename = f"{track['artists'][0]['name']} - {track['name']}.mp3"

        elif "playlist" in link:
            results = sp.playlist_tracks(link)
            playlist_name = sp.playlist(link)['name']
            filename = f"{playlist_name}.zip"
            
            for item in results['items']:
                if item['track']:
                    query = f"{item['track']['artists'][0]['name']} - {item['track']['name']} audio"
                    tasks.append({'query': query, 'folder': session_folder, 'quality': quality})

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            executor.map(download_engine, tasks)

        if "playlist" in link:
            shutil.make_archive(os.path.join(DOWNLOAD_FOLDER, session_id), 'zip', session_folder)
            download_path = os.path.join(DOWNLOAD_FOLDER, session_id + '.zip')
        else:
            files = os.listdir(session_folder)
            if files:
                download_path = os.path.join(session_folder, files[0])

        @after_this_request
        def cleanup(response):
            try:
                if os.path.exists(session_folder): shutil.rmtree(session_folder)
                if os.path.exists(download_path) and "playlist" in link: os.remove(download_path)
            except: pass
            return response

        return send_file(download_path, as_attachment=True, download_name=filename)

    except Exception as e:
        return f"Download Error: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True, port=5000)
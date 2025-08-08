import os
import json
import subprocess
import time
import threading
import requests
import libtorrent as lt
from flask import Flask, request, jsonify, send_from_directory

# --- Configuration ---
MOVIE_DIR = os.path.expanduser("~/ott_movies")
DB_FILE = os.path.join(MOVIE_DIR, "movies.json")
TMDB_API_KEY = "YOUR_TMDB_API_KEY"  # IMPORTANT: Get a free API key from https://www.themoviedb.org/
os.makedirs(MOVIE_DIR, exist_ok=True)

app = Flask(__name__, static_folder=MOVIE_DIR)

# --- Torrent Session ---
ses = lt.session({'listen_interfaces': '0.0.0.0:6881'})
torrent_handles = {}

# --- Database Helper Functions ---
def get_movie_db():
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_movie_db(db):
    with open(DB_FILE, 'w') as f:
        json.dump(db, f, indent=4)

if not os.path.exists(DB_FILE):
    save_movie_db([])

def fetch_poster(title):
    """Fetches movie poster URL from TMDB."""
    if not TMDB_API_KEY or TMDB_API_KEY == "YOUR_TMDB_API_KEY":
        return "/static/placeholder.png"
    try:
        search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={title}"
        response = requests.get(search_url)
        data = response.json()
        if data['results']:
            poster_path = data['results'][0]['poster_path']
            return f"https://image.tmdb.org/t/p/w500{poster_path}"
    except Exception:
        pass
    return "/static/placeholder.png"

# --- Background Torrent Monitor Thread ---
def monitor_torrents():
    STREAM_BUFFER_THRESHOLD = 0.05 
    while True:
        db = get_movie_db()
        db_changed = False
        for movie in db:
            if movie.get('status') in ['buffering_torrent', 'streaming_torrent'] and movie.get('filename') in torrent_handles:
                h = torrent_handles[movie['filename']]
                s = h.status()
                movie['progress'] = s.progress * 100
                
                if movie['status'] == 'buffering_torrent' and s.progress > STREAM_BUFFER_THRESHOLD:
                    movie['status'] = 'streaming_torrent'
                    db_changed = True

                if s.is_seeding:
                    movie['status'] = 'completed'
                    del torrent_handles[movie['filename']]
                    db_changed = True

        if db_changed:
            save_movie_db(db)
        time.sleep(5)

threading.Thread(target=monitor_torrents, daemon=True).start()


# --- Frontend Routes ---
@app.route('/')
def player_page():
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin_page():
    return send_from_directory('.', 'admin.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    placeholder_path = os.path.join('static', 'placeholder.png')
    if not os.path.exists(placeholder_path):
        os.makedirs('static', exist_ok=True)
    return send_from_directory('static', filename)

# --- API Routes ---
@app.route('/movies')
def get_movies():
    return jsonify(get_movie_db())

@app.route('/add_movie', methods=['POST'])
def add_movie():
    data = request.get_json()
    url = data.get('url')
    source_type = data.get('type', 'direct')

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        if source_type == 'youtube':
            get_title_cmd = ['yt-dlp', '--get-title', url]
            proc_title = subprocess.run(get_title_cmd, capture_output=True, text=True, check=True)
            title = proc_title.stdout.strip()
            
            db = get_movie_db()
            if any(m['title'] == title for m in db):
                return jsonify({'message': 'Movie already exists.'}), 200

            get_url_cmd = ['yt-dlp', '-g', '-f', 'best[ext=mp4]/best', url]
            proc_url = subprocess.run(get_url_cmd, capture_output=True, text=True, check=True)
            stream_url = proc_url.stdout.strip().split('\n')[0]

            poster_url = fetch_poster(title)
            db.append({'title': title, 'stream_url': stream_url, 'status': 'streamable', 'poster': poster_url})
            save_movie_db(db)
            return jsonify({'message': f'Added stream for: {title}'}), 201

        elif source_type == 'direct':
            title = os.path.basename(url).split('?')[0].replace('%20', ' ')
            db = get_movie_db()
            if any(m.get('stream_url') == url for m in db):
                return jsonify({'message': 'Movie already exists.'}), 200
            
            poster_url = fetch_poster(title)
            db.append({'title': title, 'stream_url': url, 'status': 'streamable', 'poster': poster_url})
            save_movie_db(db)
            return jsonify({'message': f'Added direct link for: {title}'}), 201

        elif source_type == 'torrent':
            params = {'save_path': MOVIE_DIR}
            if url.startswith('magnet:'):
                handle = lt.add_magnet_uri(ses, url, params)
            else:
                response = requests.get(url)
                response.raise_for_status()
                info = lt.torrent_info(lt.bdecode(response.content))
                handle = ses.add_torrent({'ti': info, 'save_path': MOVIE_DIR})
            
            handle.set_flags(lt.torrent_flags.sequential_download)
            while not handle.has_metadata(): time.sleep(0.1)
            
            ti = handle.get_torrent_info()
            title = ti.name()
            filename = ti.name()

            db = get_movie_db()
            if any(m.get('title') == title for m in db):
                 return jsonify({'message': 'Torrent already in library.'}), 200

            poster_url = fetch_poster(title)
            db.append({'title': title, 'filename': filename, 'status': 'buffering_torrent', 'poster': poster_url, 'progress': 0})
            save_movie_db(db)
            torrent_handles[filename] = handle
            return jsonify({'message': f'Buffering torrent for: {title}'}), 202

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Video Streaming Route (Now only for torrents) ---
@app.route('/video/<path:filename>')
def stream_video(filename):
    full_path = os.path.join(MOVIE_DIR, filename)
    if os.path.isdir(full_path):
        video_file, max_size = "", -1
        for root, _, files in os.walk(full_path):
            for f in files:
                if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
                    file_path = os.path.join(root, f)
                    size = os.path.getsize(file_path)
                    if size > max_size:
                        max_size, video_file = size, os.path.relpath(file_path, MOVIE_DIR)
        if video_file:
            return send_from_directory(MOVIE_DIR, video_file, conditional=True)
        else:
            return "No video file found in torrent", 404
    else:
        return send_from_directory(MOVIE_DIR, filename, conditional=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

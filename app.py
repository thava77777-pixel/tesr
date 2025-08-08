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
    return "/static/placeholder.png" # A default placeholder

# --- Background Torrent Downloader Thread ---
def monitor_torrents():
    while True:
        db = get_movie_db()
        db_changed = False
        for movie in db:
            if movie.get('status') == 'downloading_torrent' and movie['filename'] in torrent_handles:
                h = torrent_handles[movie['filename']]
                s = h.status()
                movie['progress'] = s.progress * 100
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
        if source_type == 'direct' or source_type == 'youtube':
            # Use yt-dlp for both direct HTTP links and YouTube
            get_info_cmd = ['yt-dlp', '--get-title', '--get-filename', '-o', '%(title)s.%(ext)s', url]
            proc = subprocess.run(get_info_cmd, capture_output=True, text=True, check=True)
            output = proc.stdout.strip().split('\n')
            title = output[0]
            filename = output[1]
            
            db = get_movie_db()
            if any(m['filename'] == filename for m in db):
                return jsonify({'message': 'Movie already exists.'}), 200

            poster_url = fetch_poster(title)
            db.append({'title': title, 'filename': filename, 'status': 'downloading', 'poster': poster_url, 'progress': 0})
            save_movie_db(db)

            def download_direct():
                download_cmd = ['yt-dlp', '-o', os.path.join(MOVIE_DIR, filename), url]
                subprocess.run(download_cmd)
                db = get_movie_db()
                for m in db:
                    if m['filename'] == filename:
                        m['status'] = 'completed'
                        break
                save_movie_db(db)
            
            threading.Thread(target=download_direct).start()
            return jsonify({'message': f'Download started for: {title}'}), 202

        elif source_type == 'torrent':
            params = {'save_path': MOVIE_DIR}
            if url.startswith('magnet:'):
                handle = lt.add_magnet_uri(ses, url, params)
            else: # Assuming it's a .torrent file link
                response = requests.get(url)
                response.raise_for_status()
                e = lt.bdecode(response.content)
                info = lt.torrent_info(e)
                handle = ses.add_torrent({'ti': info, 'save_path': MOVIE_DIR})

            ti = handle.get_torrent_info()
            title = ti.name()
            filename = ti.name() # The torrent client creates a folder or file with this name

            db = get_movie_db()
            if any(m['title'] == title for m in db):
                 return jsonify({'message': 'Torrent already in library.'}), 200

            poster_url = fetch_poster(title)
            db.append({'title': title, 'filename': filename, 'status': 'downloading_torrent', 'poster': poster_url, 'progress': 0})
            save_movie_db(db)
            torrent_handles[filename] = handle

            return jsonify({'message': f'Torrent download started for: {title}'}), 202

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Video Streaming Route ---
@app.route('/video/<path:filename>')
def stream_video(filename):
    # For torrents, the filename might be a directory. We need to find the largest video file inside.
    full_path = os.path.join(MOVIE_DIR, filename)
    if os.path.isdir(full_path):
        video_file = ""
        max_size = -1
        for root, _, files in os.walk(full_path):
            for f in files:
                if f.lower().endswith(('.mp4', '.mkv', '.avi')):
                    file_path = os.path.join(root, f)
                    size = os.path.getsize(file_path)
                    if size > max_size:
                        max_size = size
                        # We need the path relative to MOVIE_DIR
                        video_file = os.path.relpath(file_path, MOVIE_DIR)
        if video_file:
            return send_from_directory(MOVIE_DIR, video_file)
        else:
            return "No video file found in torrent", 404
    else:
        return send_from_directory(MOVIE_DIR, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)


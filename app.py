from flask import Flask, render_template, request, jsonify
import requests
import re
import random
from bs4 import BeautifulSoup
import logging
import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Configure logging for debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)  # Generate a random secret key for session management

# --- Configuration ---
# Replace these placeholders with your actual API credentials
GENIUS_ACCESS_TOKEN = 'KNO3CYd8TBY9jTtbTFU0JU9aWP4A7gkaZkNGat7Uny2d-08gv0QieJMf3S9ACVyAH9GMS1k45IEx7i_FSqOfZQ'
SPOTIFY_CLIENT_ID = '1f83046772594f539c242ff92aa3d04f'
SPOTIFY_CLIENT_SECRET = '0d9bd89723454ee1a903b1d668d1cd4b'

GENIUS_API_URL = 'https://api.genius.com/search'
REQUEST_TIMEOUT = 10  # Timeout for API requests in seconds

# Initialize Spotify client with Client Credentials Flow (no user authentication required)
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))

# --- Conversational Intents ---
# Predefined responses for common user inputs
INTENTS = {
    r'\b(hello|hi|hey)\b': ['🎵 Hello! How can I help you with music today?'],
    r'\bhow are you\b': ['🤖 I\'m a bot, always ready to help with music!'],
    r'\b(what can you do|help)\b': ['I can fetch song lyrics and Spotify previews! Try "Lyrics for Hotel California by Eagles"'],
    r'\b(thank|thanks)\b': ['You\'re welcome! 🎶'],
    r'\b(bye|goodbye)\b': ['Goodbye! Enjoy the music! 🎵']
}

# --- Helper Functions ---

def check_intent(message):
    """Check if the message matches a conversational intent and return a response."""
    message_lower = message.lower()
    for pattern, responses in INTENTS.items():
        if re.search(pattern, message_lower, re.IGNORECASE):
            logging.info(f"Matched intent: {pattern}")
            return random.choice(responses)
    return None

def extract_song_info(text):
    """Extract song title and artist from user input using regex patterns."""
    patterns = [
        r'(?:lyrics for|find|get)?\s*(?P<title>.+?)\s+by\s+(?P<artist>.+)',  # e.g., "Lyrics for Song by Artist"
        r'(?P<artist>.+?)\s+-\s+(?P<title>.+)',                             # e.g., "Artist - Song"
        r'(?P<title>.+?)\s+-\s+(?P<artist>.+)',                             # e.g., "Song - Artist"
        r'(?P<title>.+?)\s+by\s+(?P<artist>.+)',                            # e.g., "Song by Artist"
        r'(?P<title>.+?)\s+from\s+(?P<artist>.+)',                          # e.g., "Song from Artist"
        r'(?P<title>.+?)\s+lyrics\s*$',                                     # e.g., "Song lyrics"
        r'(?P<title>.+?)\s+lyrics\s+for\s+(?P<artist>.+)',                  # e.g., "Song lyrics for Artist"
        r'(?P<title>.+?)\s+by\s+(?P<artist>.+?)\s+lyrics\s*$',              # e.g., "Song by Artist lyrics"
        r'(?P<title>.+?)\s+by\s+(?P<artist>.+?)\s*$',                       # e.g., "Song by Artist"
    ]
    text_norm = text.strip()
    for pattern in patterns:
        match = re.search(pattern, text_norm, re.IGNORECASE)
        if match:
            title = re.sub(r'^(lyrics for|lyrics|song)\s+', '', match.group('title').strip(), flags=re.IGNORECASE)
            artist = re.sub(r'^(by|from)\s+', '', match.group('artist').strip(), flags=re.IGNORECASE)
            if title and artist:
                return title, artist
    return text_norm, None  # Fallback: treat the whole input as song title if no artist is detected

def search_genius(song_name, artist_name=None):
    headers = {'Authorization': f'Bearer {GENIUS_ACCESS_TOKEN}'}
    query = f"{song_name} {artist_name}" if artist_name else song_name
    params = {'q': query}

    try:
        response = requests.get(GENIUS_API_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        hits = data.get('response', {}).get('hits', [])
        for hit in hits:
            if hit.get('type') != 'song':
                continue
            song_info = hit.get('result', {})
            found_title = song_info.get('title', '').lower()
            found_artist = song_info.get('primary_artist', {}).get('name', '').lower()

            # Relaxed match
            if song_name.lower() in found_title or found_title in song_name.lower():
                if not artist_name or artist_name.lower() in found_artist:
                    return {
                        'url': song_info.get('url'),
                        'title': song_info.get('title', 'Unknown Title'),
                        'artist': song_info.get('primary_artist', {}).get('name', 'Unknown Artist'),
                        'cover_art': song_info.get('header_image_thumbnail_url', song_info.get('song_art_image_thumbnail_url'))
                    }
        return None
    except Exception as e:
        logging.error(f"Genius API error: {e}")
        return None


def scrape_lyrics(url):
    """Scrape lyrics from a Genius song page."""
    if not url:
        return None
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://genius.com/'
        })
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        lyrics_containers = soup.find_all('div', attrs={'data-lyrics-container': 'true'})
        if not lyrics_containers:
            return None
        lyrics = '\n\n'.join(
            re.sub(r'\[.*?\]\n?', '', container.get_text(separator='\n').strip()).strip()
            for container in lyrics_containers
            if container.get_text().strip()
        )
        return lyrics or None
    except Exception as e:
        logging.error(f"Lyrics scraping error: {e}")
        return None

def search_spotify_track(song_name, artist_name=None):
    """Search Spotify for a track using the song title and optional artist."""
    try:
        query = f"{song_name} {artist_name}" if artist_name else song_name
        results = sp.search(q=query, type='track', limit=1)  # Limit to 1 result for simplicity
        tracks = results['tracks']['items']
        if tracks:
            track = tracks[0]
            return {
                'spotify_album_art': track['album']['images'][0]['url'] if track['album']['images'] else None,
                'preview_url': track.get('preview_url'),
                'spotify_url': track['external_urls']['spotify']
            }
        return {}
    except Exception as e:
        logging.error(f"Spotify search error: {e}")
        return {}

# --- Routes ---

@app.route('/')
def index():
    """Serve the main page."""
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def handle_chat():
    """Handle incoming chat messages and return appropriate responses."""
    message = request.form.get('message', '').strip()
    if not message:
        return jsonify({'type': 'error', 'content': '⚠️ Please enter a message!'})

    # Check for conversational intents first
    if intent_response := check_intent(message):
        return jsonify({'type': 'message', 'content': intent_response})

    # Handle lyrics request
    song_name, artist_name = extract_song_info(message)
    genius_data = search_genius(song_name, artist_name)
    if not genius_data:
        return jsonify({
            'type': 'error',
            'content': f"❌ Couldn't find '{song_name}'" + (f" by '{artist_name}'" if artist_name else "")
        })

    lyrics = scrape_lyrics(genius_data['url'])
    spotify_data = search_spotify_track(song_name, artist_name)

    # Construct response with all available data
    response = {
        'type': 'lyrics',
        'title': genius_data['title'],
        'artist': genius_data['artist'],
        'content': lyrics or '_(Lyrics unavailable)_',
        'url': genius_data['url'],
        'cover_art': genius_data['cover_art'],
        'spotify_album_art': spotify_data.get('spotify_album_art'),
        'preview_url': spotify_data.get('preview_url'),
        'spotify_url': spotify_data.get('spotify_url')
    }
    return jsonify(response)

# --- Run the App ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
import os
import re
import random
import logging
from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from pyngrok import ngrok  # Import ngrok
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)
CORS(app)


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# API credentials
GENIUS_ACCESS_TOKEN = 'Zy31hHGwyHWgGusNTNpQnoSZQLJO4AvuuFTJBAK-KSBIGjGkfG8J_-rptg20PHVH'
SPOTIFY_CLIENT_ID = '1f83046772594f539c242ff92aa3d04f'
SPOTIFY_CLIENT_SECRET = '0d9bd89723454ee1a903b1d668d1cd4b'

# Initialize Spotify client
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

# Conversational intents
INTENTS = {
    r'\b(hello|hi|hey)\b': ['🎵 Hello! How can I help you with music today?'],
    r'\bhow are you\b': ['🤖 I\'m a bot, always ready to help with music!'],
    r'\b(what can you do|help)\b': ['I can fetch song lyrics and Spotify previews! Try "Lyrics for Hotel California by Eagles"'],
    r'\b(thank|thanks)\b': ['You\'re welcome! 🎶'],
    r'\b(bye|goodbye)\b': ['Goodbye! Enjoy the music! 🎵']
}

def check_intent(message):
    message_lower = message.lower()
    for pattern, responses in INTENTS.items():
        if re.search(pattern, message_lower, re.IGNORECASE):
            return random.choice(responses)
    return None

def extract_song_info(text):
    patterns = [
        r'(?:lyrics for|find|get)?\s*(?P<title>.+?)\s+by\s+(?P<artist>.+)',
        r'(?P<artist>.+?)\s+-\s+(?P<title>.+)',
        r'(?P<title>.+?)\s+-\s+(?P<artist>.+)',
        r'(?P<title>.+?)\s+by\s+(?P<artist>.+)',
        r'(?P<title>.+?)\s+from\s+(?P<artist>.+)',
        r'(?P<title>.+?)\s+lyrics\s*$',
        r'(?P<title>.+?)\s+lyrics\s+for\s+(?P<artist>.+)',
        r'(?P<title>.+?)\s+by\s+(?P<artist>.+?)\s+lyrics\s*$',
        r'(?P<title>.+?)\s+by\s+(?P<artist>.+?)\s*$',
        r'(?P<title>.+?)\s+from\s+(?P<artist>.+?)\s*$',
        r'(?P<title>.+?)\s+by\s+(?P<artist>.+?)\s+lyrics\s*$',
        r'(?P<title>.+?)\s+from\s+(?P<artist>.+?)\s+lyrics\s*$',
        r'(?P<title>.+?)\s+lyrics\s*$',
        r'(?P<title>.+?)\s+lyrics\s+for\s+(?P<artist>.+)',
        r'(?P<title>.+?)\s+lyrics\s+by\s+(?P<artist>.+)',
    ]
    text_norm = text.strip()
    for pattern in patterns:
        match = re.search(pattern, text_norm, re.IGNORECASE)
        if match:
            title = re.sub(r'^(lyrics for|lyrics|song)\s+', '', match.group('title').strip(), re.IGNORECASE)
            artist = re.sub(r'^(by|from)\s+', '', match.group('artist').strip(), re.IGNORECASE) if match.groupdict().get('artist') else None
            return title, artist
    return text_norm, None

def search_genius(song_name, artist_name=None):
    headers = {'Authorization': f'Bearer {GENIUS_ACCESS_TOKEN}'}
    params = {'q': f'{song_name} {artist_name}' if artist_name else song_name}

    try:
        response = requests.get('https://api.genius.com/search', headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        for hit in data.get('response', {}).get('hits', []):
            if hit.get('type') == 'song':
                song = hit.get('result', {})
                primary_artist = song.get('primary_artist', {}).get('name', '').lower()

                if artist_name and artist_name.lower() not in primary_artist:
                    continue

                # Get cover art from Genius with multiple fallbacks
                cover_art = (
                    song.get('header_image_thumbnail_url') or
                    song.get('song_art_image_thumbnail_url') or
                    song.get('song_art_image_url') or
                    song.get('header_image_url') or
                    ''
                )

                return {
                    'url': song.get('url'),
                    'title': song.get('title'),
                    'artist': song.get('primary_artist', {}).get('name'),
                    'cover_art': cover_art
                }
        return None
    except Exception as e:
        logging.error(f"Genius API error: {e}")
        return None

def scrape_lyrics(url):
    try:
        response = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        })
        soup = BeautifulSoup(response.text, 'html.parser')

        # Try different lyric container selectors
        lyrics_div = soup.find('div', class_='lyrics') or \
                     soup.find('div', attrs={'data-lyrics-container': 'true'})

        if lyrics_div:
            lyrics = '\n'.join([div.get_text(separator='\n').strip() for div in lyrics_div])
            return re.sub(r'\[.*?\]', '', lyrics).strip()
        return None
    except Exception as e:
        logging.error(f"Lyrics scraping error: {e}")
        return None

def search_spotify_track(song_name, artist_name=None):
    try:
        results = sp.search(
            q=f'{song_name} {artist_name}' if artist_name else song_name,
            type='track',
            limit=1
        )
        if tracks := results['tracks']['items']:
            track = tracks[0]
            return {
                'album_art': track['album']['images'][0]['url'] if track['album']['images'] else None,
                'preview_url': track.get('preview_url'),
                'spotify_url': track['external_urls']['spotify']
            }
        return {}
    except Exception as e:
        logging.error(f"Spotify error: {e}")
        return {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def handle_chat():
    message = request.form.get('message', '').strip()

    if not message:
        return jsonify({'type': 'error', 'content': 'Please enter a message!'})

    if intent_response := check_intent(message):
        return jsonify({'type': 'message', 'content': intent_response})

    song_name, artist_name = extract_song_info(message)
    if not song_name:
        return jsonify({'type': 'error', 'content': 'Please specify a song!'})

    genius_data = search_genius(song_name, artist_name)
    if not genius_data:
        return jsonify({'type': 'error', 'content': 'Lyrics not found!'})

    lyrics = scrape_lyrics(genius_data['url'])
    spotify_data = search_spotify_track(genius_data['title'], genius_data['artist'])

    # Combine cover art sources
    album_art = spotify_data.get('album_art') or genius_data.get('cover_art')

    return jsonify({
        'type': 'lyrics',
        'title': genius_data['title'],
        'artist': genius_data['artist'],
        'content': lyrics or 'Lyrics unavailable',
        'album_art': album_art,
        'preview_url': spotify_data.get('preview_url'),
        'spotify_url': spotify_data.get('spotify_url')
    })

if __name__ == '__main__':
    # Only run ngrok if developing locally
    if os.environ.get('RAILWAY_ENVIRONMENT') is None:  # Not running on Railway
        public_url = ngrok.connect(5000)
        print(" * ngrok tunnel:", public_url)
    
    # Use Railway's PORT or fallback to 5000 for local development
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)  # Disable debug in production

import streamlit as st
import requests
import json
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, parse_qs, urlparse

# Page config
st.set_page_config(
    page_title="VK Video Downloader",
    page_icon="🎥",
    layout="centered"
)

# Initialize session state for cookies
if 'vk_cookies' not in st.session_state:
    st.session_state.vk_cookies = None

# Custom CSS
st.markdown("""
<style>
.main {
    padding: 2rem;
}
.stButton > button {
    width: 100%;
    background-color: #4a76a8;
    color: white;
}
.stButton > button:hover {
    background-color: #3d6898;
}
.cookie-input {
    margin-bottom: 1rem;
}
.download-link {
    display: inline-block;
    padding: 0.5rem 1rem;
    background-color: #4a76a8;
    color: white;
    text-decoration: none;
    border-radius: 4px;
    margin: 0.5rem 0;
}
.download-link:hover {
    background-color: #3d6898;
}
.quality-info {
    margin: 1rem 0;
    padding: 1rem;
    border: 1px solid #ddd;
    border-radius: 4px;
}
</style>
""", unsafe_allow_html=True)

def format_size(size_bytes):
    """Format file size in bytes to human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"

def get_file_size(url, session):
    """Get file size using HEAD request."""
    try:
        response = session.head(url)
        if response.ok:
            return int(response.headers.get('content-length', 0))
    except:
        pass
    return 0

def parse_cookies(cookie_string):
    """Parse cookie string into a dictionary."""
    cookies = {}
    if cookie_string:
        pairs = cookie_string.split(';')
        for pair in pairs:
            key, value = pair.strip().split('=', 1)
            cookies[key] = value
    return cookies

def extract_video_id(url):
    """Extract video ID from VK video URL."""
    patterns = [
        r'video(-?\d+_\d+)',  # Standard video URL pattern
        r'video_ext.php\?oid=(-?\d+)&id=(\d+)',  # External video URL pattern
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            if len(match.groups()) == 1:
                return match.group(1)
            else:
                return f"{match.group(1)}_{match.group(2)}"
    return None

def parse_video_data(json_data, session):
    """Parse video data from JSON response similar to userscript."""
    try:
        # Find the video player data
        payload = json_data.get('payload', [])
        if not payload or len(payload) < 2:
            return None

        video_data = None
        # Find the item with video player info
        for item in payload[1]:
            if isinstance(item, dict) and item.get('player'):
                video_data = item
                break

        if not video_data or not video_data.get('player'):
            return None

        player = video_data['player']
        if player.get('type') != 'vk':
            return None

        params = player['params'][0]

        # Extract video sources
        sources = {}
        for key in params:
            # Look for both url and cache patterns
            if key.startswith('url') or key.startswith('cache'):
                quality = key.replace('url', '').replace('cache', '')
                if quality.isdigit():
                    url = params[key]
                    size = get_file_size(url, session)
                    sources[f"mp4_{quality}"] = {
                        'url': url,
                        'size': size,
                        'size_formatted': format_size(size)
                    }

        # Extract HLS stream if available
        if params.get('hls'):
            sources['hls'] = {'url': params['hls']}

        return {
            "title": params.get('md_title', 'Untitled'),
            "files": sources,
            "duration": params.get('duration', 0),
            "author": params.get('md_author', '')
        }

    except Exception as e:
        st.error(f"Error parsing video data: {str(e)}")
        return None

def get_video_info(url):
    """Get video information by parsing the video page."""
    try:
        # Common headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://vk.com/',
            'X-Requested-With': 'XMLHttpRequest'
        }

        # Create session to maintain cookies
        session = requests.Session()
        session.headers.update(headers)

        # Add cookies if available
        if st.session_state.vk_cookies:
            session.cookies.update(st.session_state.vk_cookies)

        # Get video ID
        video_id = extract_video_id(url)
        if not video_id:
            st.error("Could not extract video ID from URL")
            return None

        # Make request to al_video.php
        data = {
            'act': 'show',
            'al': 1,
            'video': video_id,
            'autoplay': 0,
            'module': '',
            'list': ''
        }

        response = session.post(
            'https://vk.com/al_video.php',
            data=data,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest'
            }
        )

        if not response.ok:
            st.error("Failed to fetch video info")
            return None

        try:
            json_data = response.json()
        except:
            # Try parsing embedded JSON from HTML response
            json_match = re.search(r'<!json>(.+?)<!>', response.text)
            if json_match:
                json_data = json.loads(json_match.group(1))
            else:
                st.error("Could not parse server response")
                return None

        video_info = parse_video_data(json_data, session)
        if not video_info:
            # Fallback to parsing page HTML if API fails
            response = session.get(url)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Find video title
            title_elem = soup.find('div', {'class': 'mv_title'}) or soup.find('div', {'class': 'VideoPageInfoRow__title'})
            title = title_elem.text.strip() if title_elem else "Untitled Video"

            # Find video sources
            sources = {}

            # Try to find video data in page source
            video_data_match = re.search(r'"url(\d+)":"([^"]+)"', response.text)
            if video_data_match:
                quality = video_data_match.group(1)
                video_url = video_data_match.group(2).replace('\\', '')
                size = get_file_size(video_url, session)
                sources[f"mp4_{quality}"] = {
                    'url': video_url,
                    'size': size,
                    'size_formatted': format_size(size)
                }

            video_info = {
                "title": title,
                "files": sources
            }

        return video_info

    except Exception as e:
        st.error(f"Error fetching video info: {str(e)}")
        return None

def download_video(url, filename):
    """Download video from URL."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://vk.com/',
            'X-Requested-With': 'XMLHttpRequest'
        }

        # Create session with cookies if available
        session = requests.Session()
        session.headers.update(headers)
        if st.session_state.vk_cookies:
            session.cookies.update(st.session_state.vk_cookies)

        response = session.get(url, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024
        progress_bar = st.progress(0)

        with open(filename, 'wb') as f:
            downloaded = 0
            for data in response.iter_content(block_size):
                f.write(data)
                downloaded += len(data)
                if total_size:
                    progress = int((downloaded / total_size) * 100)
                    progress_bar.progress(progress / 100)

        return True
    except Exception as e:
        st.error(f"Error downloading video: {str(e)}")
        return False

# Main app
st.title("VK Video Downloader")
st.markdown("Download videos from VK.com easily!")

# Cookie input section
with st.expander("🔐 Add VK Cookies (Optional - Required for private videos)"):
    st.markdown("""
    To download private videos, you need to provide your VK cookies:
    1. Log in to VK.com in your browser
    2. Open Developer Tools (F12)
    3. Go to Network tab
    4. Copy the 'Cookie' header from any request to vk.com
    """)
    cookie_input = st.text_area(
        "Enter your VK cookies here:",
        help="Paste your VK cookies to enable downloading private videos",
        key="cookie_input"
    )
    if st.button("Save Cookies"):
        if cookie_input:
            st.session_state.vk_cookies = parse_cookies(cookie_input)
            st.success("Cookies saved successfully!")
        else:
            st.session_state.vk_cookies = None
            st.info("Cookies cleared.")

# Input field for video URL
video_url = st.text_input("Enter VK video URL:", placeholder="https://vk.com/video...")

if video_url:
    video_info = get_video_info(video_url)

    if video_info:
        st.subheader(video_info["title"])
        if video_info.get("author"):
            st.write(f"Author: {video_info['author']}")
        if video_info.get("duration"):
            st.write(f"Duration: {video_info['duration']} seconds")

        # Display available qualities and download buttons
        available_qualities = {k: v for k, v in video_info["files"].items() if v and k != 'hls'}

        if available_qualities:
            st.write("### Available Qualities")

            for quality, info in available_qualities.items():
                with st.container():
                    st.markdown(f"""
                    <div class="quality-info">
                        <h4>{quality.replace('mp4_', '')}p</h4>
                        <p>Size: {info['size_formatted']}</p>
                        <a href="{info['url']}" class="download-link" target="_blank">Download {quality.replace('mp4_', '')}p</a>
                    </div>
                    """, unsafe_allow_html=True)

                    # Also show copyable URL
                    st.code(info['url'], language=None)
        else:
            if st.session_state.vk_cookies:
                st.error("No download links available. The video might be private or deleted.")
            else:
                st.warning("No download links available. If this is a private video, try adding your VK cookies above.")

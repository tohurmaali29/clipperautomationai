import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # API Keys
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY')
    WHISPER_MODEL = os.environ.get('WHISPER_MODEL', 'tiny')
    WHISPER_DEVICE = os.environ.get('WHISPER_DEVICE', 'cpu')
    WHISPER_COMPUTE_TYPE = os.environ.get('WHISPER_COMPUTE_TYPE', 'int8')
    WHISPER_MAX_AUDIO_SECONDS = int(os.environ.get('WHISPER_MAX_AUDIO_SECONDS', '300'))
    WHISPER_CHUNK_SECONDS = int(os.environ.get('WHISPER_CHUNK_SECONDS', '180'))
    
    # GCP Configuration
    GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
    GOOGLE_CLOUD_REGION = os.environ.get('GOOGLE_CLOUD_REGION', 'us-central1')
    GOOGLE_APPLICATION_CREDENTIALS = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    
    # File Configuration
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

# AI Video Clipper

Project skripsi untuk menganalisis video YouTube, memilih momen yang layak dijadikan short clip, lalu menghasilkan video vertikal dengan subtitle otomatis.

## Status Sekarang

- Backend utama: FastAPI di `main.py`
- Entry point lama `app.py` masih ada sebagai wrapper kompatibilitas
- Dashboard web sudah terhubung ke backend
- Flow `analyze -> pilih clip -> generate -> download` sudah jalan
- Rendering clip MP4 dengan FFmpeg sudah berhasil diuji end-to-end
- Sistem sudah punya indikator `Live Mode` vs `Demo Mode`

## Fitur

- Analisis video YouTube melalui transkripsi audio otomatis dengan Whisper
- Rekomendasi clip berbasis Gemini dengan fallback mock analysis
- Generate subtitle format `.ass`
- Crop video ke format vertikal `9:16`
- Hardcode subtitle ke hasil video
- Dashboard sederhana untuk kebutuhan demo

## Arsitektur

```text
.
|-- app.py
|-- config.py
|-- ffmpeg.exe
|-- main.py
|-- requirements.txt
|-- services/
|   |-- gemini_service.py
|   |-- subtitle_service.py
|   |-- transcript_service.py
|   `-- video_service.py
|-- static/
|   |-- css/style.css
|   `-- js/app.js
|-- templates/
|   `-- index.html
|-- tests/
|   `-- test_smoke.py
`-- uploads/
```

## Menjalankan Project

Gunakan interpreter dari virtual environment supaya dependency yang dipakai konsisten.

### 1. Install dependency

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Siapkan environment

```powershell
Copy-Item .env.example .env
```

Isi `.env` minimal seperti ini:

```env
SECRET_KEY=your-secret-key
GEMINI_API_KEY=your-gemini-api-key
YOUTUBE_API_KEY=your-youtube-api-key
```

Untuk transkripsi audio dari YouTube maupun file lokal, aktifkan Whisper lokal:

```env
WHISPER_MODEL=tiny
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_MAX_AUDIO_SECONDS=0
WHISPER_CHUNK_SECONDS=120
```

Catatan:
`WHISPER_MAX_AUDIO_SECONDS=0` berarti seluruh durasi audio akan ditranskrip. Isi nilai lain seperti `600` atau `1200` jika ingin membatasi analisis agar lebih cepat.

### 3. Jalankan aplikasi

```powershell
.\.venv\Scripts\python.exe main.py
```

### 4. Buka dashboard

```text
http://localhost:5000
```

## Command Berguna

Smoke test:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_smoke
```

Health check cepat:

```powershell
.\.venv\Scripts\python.exe -c "import asyncio, main; print(asyncio.run(main.health_check()))"
```

## Endpoint

- `GET /` dashboard utama
- `GET /health` health check
- `POST /analyze` analisis transcript dan rekomendasi clip
- `POST /generate-clip` generate video final
- `POST /generate-subtitle` generate subtitle `.ass`
- `GET /download/{filename}` download hasil video

## Demo Mode

Aplikasi sekarang bisa tetap dipresentasikan walau layanan eksternal sedang gagal.

- Jika transcript YouTube gagal, sistem pakai transcript mock
- Jika Gemini gagal, sistem pakai clip recommendation mock
- UI akan menandai apakah hasil datang dari `Live Mode` atau `Demo Mode`

## Known Limitations


- Download audio YouTube masih bergantung pada akses publik video dan bisa terkena pembatasan dari YouTube
- Fallback Whisper akan download model saat pertama kali dipakai
- Jika seluruh durasi audio diproses, waktu analisis akan meningkat signifikan pada video yang panjang
- Gemini API bisa gagal jika API key diblok atau belum aktif untuk service terkait
- Beberapa file cache Python di Windows bisa terkunci saat proses masih aktif
- Folder `uploads/` berisi artefak hasil generate dan aman dibersihkan jika tidak dibutuhkan

## Catatan Repo

- `.env` tidak boleh masuk repository
- `uploads/`, file test output, dan `__pycache__` termasuk artefak yang tidak perlu disimpan
- `utils/json_utils.py` dan `utils/time_utils.py` saat ini belum dipakai oleh flow utama

## Untuk Skripsi

Struktur project sudah cukup enak dijelaskan di bab implementasi:

- `transcript_service.py` untuk akuisisi transcript
- `gemini_service.py` untuk analisis AI berbasis Gemini API
- `subtitle_service.py` untuk pembentukan subtitle
- `video_service.py` untuk trimming, crop, dan hardcode subtitle
- `main.py` untuk orkestrasi endpoint backend

Project ini ditujukan untuk kebutuhan edukasi dan penelitian.

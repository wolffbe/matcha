# Media Matching

Docker-based media matching system using perceptual hashing (PDQ for images/video, Chromaprint for audio), Whisper transcription, and Qdrant vector search.

![Calibration test image](./docs/calibrate_image_base.png)

## Architecture
```
Client → Nginx (LB) → Hashing API (scalable) → Redis Queue → Index Worker → Qdrant
```

| Service | Purpose |
|---------|---------|
| nginx | Load balancer |
| hashing | Compute hashes, fingerprints, transcripts (stateless, scalable) |
| index | Qdrant operations (single instance) |
| qdrant | Vector storage |
| redis | Message queue |

## Setup
```bash
cp .env.example .env  # Add OPENAI_API_KEY
docker-compose up -d --scale hashing=3
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/hash` | Index media file |
| POST | `/match` | Find matches |
| DELETE | `/delete/{item_id}` | Remove item |
| POST | `/reset` | Clear index |
| GET | `/stats` | Index statistics |

### Hash
```bash
curl -X POST -F "file=@video.mp4" http://localhost:8000/hash
```

### Match
```bash
curl -X POST -F "file=@query.mp4" \
  "http://localhost:8000/match?video_hamming_distance=28&audio_hamming_distance=60"
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `image_hamming_distance` | 20 | Max distance for images (0-256) |
| `video_hamming_distance` | 28 | Max distance for video frames (0-256) |
| `audio_hamming_distance` | 60 | Max distance for audio (0-256) |

### Response
```json
[{
  "item_id": "a1b2c3...",
  "status": "near_match",
  "video_match_percent": 86.0,
  "audio_match_percent": 90.0,
  "video_hamming_distance": 28,
  "audio_hamming_distance": 60
}]
```

Status: `exact_match` | `near_match` | `no_match`

## Hamming distance calibration
Image, audio and video [calibration scripts](./calibration/) run variations of [artificially generated media](./docs/) across different hamming distances to identify optimal values for thresholds of 90% for images and 85% for audio, video and transcripts.

### Run

Start application locally and
```
python calibration/calibrate_audio.py
python calibration/calibrate_image.py
python calibration/calibrate_video.py
```

### Results

Given the latest results for each modality exported [here](./calibration/results/), the following distances are recommended:

| Modality | Test cases | Distance | Accuracy | Duration | Comment
|----------|------------|----------|----------|----------|---------|
| image    | 53 | 20       | 70%      | ~9s    | Calibrated exhaustively from 0-30
| audio    | 39 | 28       | 51%      | ~21m      | Calibrated only with 28 with 3s segment sizes and 0.5s hops; requires more testing with larger and smaller distances (20, 30, 40, 50, 70, 80, 90, 100); segment and hop size seem reasonable
| video    | 145 | 28/60       | 51%        | ~45m        | Calibrated only with 28 for video and 60 for audio; additional combinations of audio and image distances after testing both modalities individually could be further tested

Transcripts are shingled at size 3, and LSH candidates retrieved at a threshold of 0.5. Both value are common.

Exhaustively calibrated distances should be set as defaults in `.env` and the [config](index/app/config.py) of the index service.
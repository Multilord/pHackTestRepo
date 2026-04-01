# HomeGrow AI Engine

AI-powered plant recommendation and disease diagnosis backend for HomeGrow — a urban gardening assistant built for tropical Southeast Asian home growers.

---

## What This Does

HomeGrow AI Engine is a FastAPI backend that connects directly to MongoDB Atlas and Google Gemini AI. It handles:

- **Plant recommendations** — given a user's growing space, sunlight, and goal, it fetches plants from the database, filters them by real growing conditions, and uses Gemini AI to rank and explain the best matches
- **Disease diagnosis** — analyses a plant photo using Gemini Vision and returns a structured diagnosis with problem, cause, severity, solution, and confidence score
- **User plant tracking** — lets users add plants to their garden, log activities (watering, harvesting), and view dashboard stats
- **Plant catalogue** — serves the full plant list from MongoDB

---

## Architecture

```
Frontend / Test UI
       │
       ▼
  FastAPI (port 8000)
  ├── Google Gemini AI  (plant ranking + image diagnosis)
  └── MongoDB Atlas     (plants, recommendations, diagnoses, users)
```

There is no separate Express or Node.js backend. FastAPI is the single backend service — it owns all database reads/writes and all AI calls.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend framework | Python 3.12+ / FastAPI |
| AI provider | Google Gemini (`gemini-2.5-flash`) |
| Database | MongoDB Atlas (Motor async client) |
| Runtime | Uvicorn (ASGI) |

---

## Project Structure

```
ai-service/
├── main.py                     # App entry point, router registration
├── requirements.txt            # Python dependencies
├── .env                        # Your local secrets (never committed)
├── .env.example                # Template — copy to .env and fill in
├── test_ui.html                # Browser-based dev test console
│
├── routes/
│   ├── plants.py               # GET /api/plants
│   ├── recommend.py            # POST /api/recommend
│   ├── diagnose.py             # POST /api/diagnose
│   └── user_plants.py          # POST /api/user-plants, /api/activity, GET /api/dashboard/:userId
│
├── utils/
│   ├── db.py                   # MongoDB Motor async connection
│   └── helpers.py              # JSON parsing, serialization, base64 utilities
│
└── prompts/
    ├── recommend_system.txt    # Gemini system prompt for plant ranking
    └── diagnose_system.txt     # Gemini system prompt for disease diagnosis
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service + DB connectivity status |
| `GET` | `/api/plants` | All plants from MongoDB |
| `POST` | `/api/recommend` | AI plant recommendations → saved to DB |
| `POST` | `/api/diagnose` | Plant image diagnosis → saved to DB |
| `POST` | `/api/user-plants` | Add a plant to user's garden |
| `POST` | `/api/activity` | Log a watering/harvest/fertilizing event |
| `GET` | `/api/dashboard/{userId}` | Aggregated stats for a user |

Full interactive docs available at `http://localhost:8000/docs` when the server is running.

---

## MongoDB Collections

| Collection | Purpose |
|-----------|---------|
| `plants` | Master plant catalogue (read by AI service) |
| `users` | Registered user accounts |
| `recommendations` | Saved recommendation results per user |
| `diagnoses` | Saved plant diagnosis results per user |
| `user_plants` | Plants a user is actively growing |
| `activity_logs` | Watering, harvest, fertilizing logs |

---

## Setup

### Prerequisites

- Python 3.12 or higher
- A [Google AI Studio](https://aistudio.google.com) account (free Gemini API key)
- A [MongoDB Atlas](https://cloud.mongodb.com) cluster with a `homegrow` database

### 1. Clone the repository

```bash
git clone https://github.com/Multilord/pHackTestRepo.git
cd pHackTestRepo/ai-service
```

### 2. Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv venv
& ".\venv\Scripts\Activate.ps1"
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
MONGODB_URI=mongodb+srv://<username>:<password>@yourcluster.mongodb.net/?appName=YourApp
DB_NAME=homegrow
```

- Get a free Gemini API key at https://aistudio.google.com/apikey
- Get your MongoDB connection string from Atlas → Connect → Drivers

### 5. Run the server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The server will start at `http://localhost:8000`.

---

## Verify It's Working

**Check service and DB status:**
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "service": "HomeGrow AI Engine",
  "model": "gemini-2.5-flash",
  "db": "connected"
}
```

**Interactive API docs:**
Open `http://localhost:8000/docs` in your browser.

**Dev test console:**
Open `ai-service/test_ui.html` directly in your browser to test recommendations and diagnoses visually.

---

## Example Requests

### Get plant recommendations

```bash
curl -X POST http://localhost:8000/api/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "location": "Balcony",
    "sunlight": "Full Sun",
    "goal": "Cooking herbs",
    "sunlightHours": 6,
    "temperature": 28,
    "humidity": 70
  }'
```

### Diagnose a plant

```bash
curl -X POST http://localhost:8000/api/diagnose \
  -H "Content-Type: application/json" \
  -d '{
    "image": "<base64-encoded-image>",
    "cropType": "Tomato",
    "growthStage": "Flowering",
    "symptoms": "Yellowing leaves"
  }'
```

---

## What Still Needs to Be Built

- **Authentication** — `POST /api/auth/register` and `POST /api/auth/login` endpoints using the existing `users` collection
- **Frontend integration** — connect the React/web frontend to these API endpoints
- **Image upload** — currently accepts base64 in the request body; a cloud storage integration (e.g. Cloudinary, S3) would let the frontend upload images and pass back a URL

---

## Notes

- `.env` is excluded from version control via `.gitignore` — never commit your API keys
- The `test_ui.html` file is for development testing only and will be replaced by the real frontend
- The `venv/` folder is excluded from version control

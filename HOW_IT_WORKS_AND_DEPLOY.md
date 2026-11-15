# GST Notice Responder — Architecture, Generation Guide & Deployment

This document explains how the upstream [`caloganathan/GSTresponsegenerator`](https://github.com/caloganathan/GSTresponsegenerator) repository (built on Andrej Karpathy's LLM Council) was decoded, extended with a 3-step Notice Responder UI, Google Lens-style OCR, Guest/BYOK OpenRouter support, and deployed to Cloudflare Pages.

---

## 1. How the Repository Was Decoded

### Backend (`backend/`)
- **`backend/main.py`** — FastAPI application serving:
  - Authentication: `POST /api/auth/login`, `POST /api/auth/register` (public sign-up), and `POST /api/auth/guest` (ephemeral session with `is_guest=True`, no database/file persistence).
  - Intake & OCR: `POST /api/panel/intake` accepts PDFs or images (`.png`, `.jpg`, `.jpeg`, `.webp`), extracts structured notice fields, renders page previews with bounding boxes, and generates targeted Indian GST Act clarifying questions.
  - Adversarial Deliberation (SSE): `POST /api/panel/run-inline` (used by Guest & Quick Responder) and `POST /api/panel/matters/{id}/run` stream real-time events across 4 stages.
  - Report Export: `POST /api/panel/export-inline` builds and streams a formatted Word (`.docx`) statutory reply pack in memory without saving anything to disk.
- **`backend/ocr.py`** — Local RapidOCR (`rapidocr-onnxruntime`) + PyMuPDF (`fitz`):
  - `ocr_image()` processes direct image uploads.
  - `_boxes_from_result()` converts OCR polygons into normalized `[0..1]` bounding boxes for interactive UI highlighting.
  - `render_pdf_previews()` and `_encode_preview_jpeg()` produce base64 JPEG page previews for the Lens viewer.
- **`backend/intake.py`** — Extracts GSTIN, notice type (`ASMT-10`, `DRC-01`, `SCN`, etc.), financial year, demand amounts, due date, and state; `build_clarifying_questions()` builds contextual follow-up questions under the Indian GST Act.
- **`backend/panel.py` & `backend/openrouter.py`** — 4-stage Compliance Panel:
  1. **Counsel Opening Analyses** — Four specialist counsel (Revenue, Assessee, Procedural/Limitation, Risk/Ethics) analyze the notice in parallel.
  2. **Cross-Examination** — Counsel challenge assumptions and test statutory arguments.
  3. **Chairman Determination** — Synthesizes the structured reply (`recommended_position`, `lead_argument`, `preliminary_submissions`, `defects`, `risk_flags`, `board_summary`).
  4. **Citation Verification** — Checks cited case law and CBIC circulars against live sources.
  - **BYOK OpenRouter Support**: `backend/openrouter.py` uses a `contextvars.ContextVar` populated from the `X-OpenRouter-Key` request header so each public or guest user supplies their own OpenRouter API key without storing it on the server.

### Frontend (`frontend/src/`)
- **`components/Login.jsx`** — Supports **Sign In**, **Create Account**, and **Continue as Guest (No data saved)**.
- **`components/OpenRouterKeyGate.jsx`** — Prompts the user for their OpenRouter API key (`sk-or-v1-...`) immediately after login/guest entry and stores it in browser `localStorage` (sent via `X-OpenRouter-Key`).
- **`components/QuickResponder.jsx`** — Default 3-step workflow:
  1. **Upload Notice** (drag-and-drop PDF/PNG/JPG/WEBP).
  2. **Lens Scan & Questions** (`LensScanner.jsx` overlays interactive OCR boxes on the notice; `ClarifyingQuestions.jsx` captures taxpayer facts).
  3. **GST Act Response** (streams the 4-stage SSE progress, renders the structured statutory reply in Markdown, and provides a one-click `.docx` Word download).

### Cloudflare Edge Proxy (`functions/` & `wrangler.toml`)
- **`functions/api/[[path]].js`** and **`functions/healthz.js`** — Cloudflare Pages Functions reverse-proxy `/api/*` and `/healthz` to the `BACKEND_URL` secret, preserving `Authorization`, `X-OpenRouter-Key`, and Server-Sent Events (SSE) streams.

---

## 2. Step-by-Step Local Setup & Verification

### Prerequisites
- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- Node.js 18+ and `npm`
- [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) (for tunneling local backend to Cloudflare Pages)
- Wrangler CLI (`npx wrangler`)

### Run Locally
1. **Install backend dependencies (with local OCR):**
   ```bash
   uv sync --extra ocr
   ```
2. **Start the FastAPI backend (port `8001`):**
   ```bash
   uv run python -m backend.main
   ```
   *(Leave `OPENROUTER_API_KEY` unset in `.env` if you want public/guest users to supply their own key via the UI.)*
3. **Install and build the frontend:**
   ```bash
   cd frontend
   npm install
   npm run build
   ```
4. **Run tests:**
   ```bash
   uv run pytest tests/test_lens_and_questions.py tests/test_intake.py -q
   ```

---

## 3. Step-by-Step Cloudflare Deployment

1. **Expose the local backend with Cloudflare Tunnel:**
   ```bash
   cloudflared tunnel --url http://localhost:8001
   ```
   Copy the generated `https://<random>.trycloudflare.com` URL.
2. **Set the `BACKEND_URL` secret on Cloudflare Pages:**
   ```bash
   npx wrangler pages secret put BACKEND_URL --project-name gst-notice-responder
   ```
   Paste the `https://<random>.trycloudflare.com` URL when prompted.
3. **Build and deploy to Cloudflare Pages:**
   ```bash
   cd frontend && npm run build && cd ..
   npx wrangler pages deploy frontend/dist --project-name gst-notice-responder --branch main
   ```
4. **Verify live URL:**
   - Production URL: `https://gst-notice-responder.pages.dev`
   - Health check: `https://gst-notice-responder.pages.dev/healthz`

---

## 4. Git Workflow & Adding Loganathan (`caloganathan`) as a Collaborator

Because this workspace was cloned from `https://github.com/caloganathan/GSTresponsegenerator.git`, push to your own GitHub repository and add `caloganathan` as a collaborator:

1. **Authenticate GitHub CLI:**
   ```bash
   gh auth login -h github.com
   ```
2. **Create or point `origin` to your GitHub repository:**
   ```bash
   git remote set-url origin https://github.com/<YOUR_GITHUB_USERNAME>/GSTresponsegenerator.git
   git push -u origin master
   ```
3. **Add Loganathan (`caloganathan`) as a collaborator:**
   ```bash
   gh api repos/<YOUR_GITHUB_USERNAME>/GSTresponsegenerator/collaborators/caloganathan -X PUT -f permission=push
   ```
   *(Or on GitHub.com: **Settings → Collaborators → Add people → `caloganathan`**.)*

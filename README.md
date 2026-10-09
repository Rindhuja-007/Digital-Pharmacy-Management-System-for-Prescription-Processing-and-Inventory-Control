# PharmaCare

Pharmacist-assisted digital pharmacy. A pharmacist uploads a prescription photo; the system reads it (OCR),
extracts medicine lines and **suggests** catalogue matches and substitutes. The pharmacist reviews and verifies
every line, then dispenses. Stock is deducted First-Expired-First-Out (FEFO). The software only suggests;
a human confirms everything.

```
backend/   FastAPI + SQLAlchemy 2.0 (routers -> services -> models), pytest suite
frontend/  React 18 + Vite + axios, hand-written CSS
```

## Run it

**Backend** (Python 3.11+)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                         # includes paddlepaddle + paddleocr (large)
export JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export ADMIN_APPROVAL_CODE="choose-a-code"              # lets extra admins self-approve; leave empty to disable
# optional: DATABASE_URL=postgresql+psycopg2://user:pass@host/db   (pip install psycopg2-binary)
uvicorn app.main:app --reload --port 8000               # API docs: http://localhost:8000/docs
```
**Frontend** (Node 18+)
```bash
cd frontend
npm install
npm run dev                                             # http://localhost:5173
# API elsewhere? cp .env.example .env and set VITE_API_URL
```
**First use:** open the app. With an empty database the login page offers to create the first admin
(auto-approved) or **Load demo data**: `admin / Admin@123`, `pharmacist / Pharmacist@123`, and three medicines
(Crocin 500 with zero stock, Dolo 500 with 120, Metformin 500 with 80). Demo credentials are for local use only.

**Tests:** `cd backend && python -m pytest` (in-memory SQLite, OCR mocked: no Paddle models needed).

PaddleOCR downloads its models on first use, so the first **Run OCR** click is slow. If paddle is not installed
the endpoint returns 503 with an explanatory message and everything else keeps working.

## Safety rules and where they are enforced
| Rule | Enforcement |
|---|---|
| Upload/OCR/extract/match never approve or move stock | `services/prescriptions.py` never touches `Batch`; only `services/dispensing.py` does. Tested. |
| Only pharmacist/admin verify | `require_staff` dependency on every non-public route |
| Dispense needs `confirmed_dispensing=true` | 422 otherwise (service + schema); UI adds a confirmation dialog and checkbox |
| One transaction, row locks, full rollback | `dispense()`: `SELECT ... FOR UPDATE` on batches, any exception -> `rollback()` |
| Never use expired batches; FEFO | `quantity > 0 AND expiry_date >= today`, `ORDER BY expiry_date, id` (`services/stock.py`) |
| Audit log | upload, verify, reject, create medicine, add stock, dispense (+ user/CSV/batch edits), written in the same transaction as the action |
| Verified only, once | atomic `UPDATE ... WHERE status='VERIFIED'` claims the prescription first, so a double click or race dispenses once |

## Assumptions (you asked me to state them)
- **SQLite ignores `FOR UPDATE`.** Dev on SQLite is correct for one writer; use PostgreSQL for concurrent counters.
  The atomic status claim above protects against double-dispensing on both.
- `discount` and `tax` are **absolute currency amounts**, not percentages. Currency display is INR; change `format.js`.
- Money is `Decimal` end to end and is returned as JSON **strings** (`"25.40"`). The UI only formats it for display.
- API responses omit server file paths (`image_path`); images are served by `GET /prescriptions/{id}/image`.
- OCR runs on the preprocessed image when one exists (override with `?source=original`).
- Match results are saved on **PENDING** lines as suggestions (`medicine_id`, `matched_medicine_name`, score).
  Verification still requires an explicit decision and `medicine_id` in the request body.
- A different strength than the prescription (Crocin 650 vs 500) lowers the match score by 20 and is flagged.
- Substitute detection compares active-ingredient tokens as specified; salt words (hydrochloride, sodium...) are ignored
  so "Metformin HCl" is not offered for "Cetirizine HCl". Check strength before substituting (flagged in the UI).
- Extraction: lines the blocklist drops are reported as *skipped* instead of vanishing. Quantity is a suggestion
  (doses/day x days for tablets/capsules, else 1). Strength regex uses `(?![A-Za-z])` so `1%` works.
- A VERIFIED or REJECTED prescription can be re-verified until it is DISPENSED (each save is audited).
- Rejecting a pending admin deletes the account but keeps its audit rows (user reference cleared).
- JWT secret is read from `JWT_SECRET`; if unset a random per-process one is used and a warning is logged.
- `/auth/seed-demo` works without a token only on an empty database; afterwards it needs an admin.

## Verified vs not verified
Verified here: 63 backend tests pass; frontend builds; the live server starts and handles seed, login, CORS,
upload and preprocessing. **Not verified:** real PaddleOCR output (models could not be installed in my sandbox),
PostgreSQL, and the UI in a real browser (build only, no visual check). Try one real prescription photo early:
OCR quality on handwriting is the biggest practical risk, and the parser/misread dictionary in
`services/extraction.py` will need tuning to your doctors' formats.

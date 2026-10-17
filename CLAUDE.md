# Lucid Project Guidelines (Brightspace Grade & Progress Assistant)

## System Architecture & Tech Stack
- **Backend:** Python 3.11+ (FastAPI, PyMuPDF `fitz`, Pydantic v2)
- **Frontend Target:** Chrome Extension Side Panel API (Manifest V3)
- **Frontend Styling:** Tailwind CSS, React (or vanilla JS based on implementation preference)

## Frontend Specifications & Constraints
- **Delivery:** Must use Chrome Side Panel API (`chrome.sidePanel`) providing a resizable panel (typically 320px - 480px). Layouts must be strictly fluid/responsive (e.g., `w-full`, `truncate` for long course titles); no fixed widths that trigger horizontal scrolling.
- **State Management:** Use `chrome.storage.local` to cache synced courses, extracted syllabi, and calculations. Prevent re-crawling unless the user explicitly clicks the `[ Sync ]` button.
- **UI Views & Flow:**
  1. **Home Screen:** Lists enrolled courses. Each course card shows an evaluated weight fraction progress bar (e.g., `12 / 15` - meaning 15% of the course has been evaluated and the user earned 12%), a projected grade (e.g., `80%`), and a guaranteed floor grade. Bottom action bar contains `Home` and `Sync`.
  2. **Individual Course Screen:** Drill-down view into a specific course showing a list of assessed material (e.g., Quizzes, Tests, Exams, Assignments, Wooclap participation).
  3. **Upload Fallback Dropzone:** Displays when automated Brightspace PDF extraction fails or isn't supported (e.g., external Google Doc links). Allows manual PDF upload.
- **Aesthetics:** Minimalist dark/neutral theme (e.g., slate/zinc). Use subtle borders (`border-neutral-800`), compact padding, and monospace fonts for raw numerical score badges. Progress bar fills must use high-contrast color indicators (e.g., green for completion).

## Backend Module Responsibilities
Strictly maintain decoupled boundaries. No business logic in `main.py`; no API routing in `calculator.py`.
- `schemas.py`: Pydantic data contracts (`GradeItem`, `GradingCategory`, request/response models).
- `extractor.py`: Handles raw PDF byte stream ingestion and text normalization using PyMuPDF (`fitz`) with zero disk I/O. Must process both Brightspace auto-fetches and manual dropzone uploads identically.
- `parser.py`: Passes the raw text extracted by `extractor.py` to the LLM (Claude) with strict schema enforcement to return structured `GradingCategory` lists.
- `calculator.py`: Pure math business logic. Computes `points_earned`, `evaluated_weight`, `projected_grade`, and `guaranteed_floor`.
- `main.py`: Configures FastAPI app, CORS middleware (`allow_origins=["*"]`), and exposes endpoints `/api/parse-syllabus` and `/api/calculate-standing`. Connects parser and calculator logic.

## Verified Brightspace Paths (Targeting Extraction)
- **2310:** Contents -> Start Here! -> Course outline (Embedded PDF)
- **2100:** Contents -> General Information -> Simple Syllabus (Embedded PDF)
- **2004:** Contents -> General Course Information -> Course Outline (Embedded PDF)
- **1005:** Contents -> Course Outline -> Outline (Embedded PDF)
- **1805:** Contents -> Start Here -> Course outline (External Google Doc -> Triggers Fallback Dropzone)

## Rules & Execution
- Write fully-typed, complete Python implementations. Do not leave `# TODO` placeholders.
- Always append verification assertions at the bottom of computational modules (e.g., under `if __name__ == '__main__':` in `calculator.py` to test the 12/15 progress logic).
- Run tests in the terminal to verify math and schema contracts before confirming completion.
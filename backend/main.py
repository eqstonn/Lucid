"""FastAPI entrypoint: HTTP wiring only. Logic lives in extractor, parser and calculator."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from calculator import calculate_standing
from extractor import ExtractionError, extract_text_from_pdf
from parser import ParseError, parse_syllabus_text
from schemas import CalculateStandingRequest, CourseStanding, ParseSyllabusResponse

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

app = FastAPI(title="Lucid API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _read_pdf_bytes(request: Request, file: Optional[UploadFile]) -> bytes:
    """Accept either a multipart ``file`` field or a raw ``application/pdf`` body."""
    data = await file.read() if file is not None else await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="No PDF provided (send multipart 'file' or raw PDF bytes)")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="PDF is too large")
    return data


@app.post("/api/parse-syllabus", response_model=ParseSyllabusResponse)
async def parse_syllabus(request: Request, file: Optional[UploadFile] = File(default=None)) -> ParseSyllabusResponse:
    pdf_bytes = await _read_pdf_bytes(request, file)
    try:
        text = await run_in_threadpool(extract_text_from_pdf, pdf_bytes)
        categories = await run_in_threadpool(parse_syllabus_text, text)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {exc}") from exc
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse syllabus: {exc}") from exc
    return ParseSyllabusResponse(categories=categories)


@app.post("/api/calculate-standing", response_model=CourseStanding)
def calculate_course_standing(payload: CalculateStandingRequest) -> CourseStanding:
    return calculate_standing(payload.categories)

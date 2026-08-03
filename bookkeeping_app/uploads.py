"""Shared HTTP upload adapters."""

from fastapi import HTTPException, UploadFile

from bookkeeping_app.parsers import is_valid_csv_upload


async def read_csv_upload(file: UploadFile) -> str:
    """Validate and decode one uploaded CSV file."""

    if not is_valid_csv_upload(file):
        raise HTTPException(status_code=400, detail="Invalid file type. Use a CSV file.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        return file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV file must be UTF-8 encoded") from exc

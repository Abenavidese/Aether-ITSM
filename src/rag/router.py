from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
import os
import shutil
from typing import List
from src.security.deps import get_current_user
from src.db.models import User
from src.rag.service import ingest_file, get_uploaded_files, delete_file

router = APIRouter(prefix="/tenant/knowledge", tags=["knowledge"])

UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("")
async def upload_document(
    file: UploadFile = File(...), 
    source_type: str = Form(...),
    current_user: User = Depends(get_current_user)
):
    """Uploads a PDF or TXT file to the company's knowledge base."""
    if current_user.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can modify knowledge base.")
        
    if not (file.filename.endswith(".pdf") or file.filename.endswith(".txt")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF and TXT files are supported.")
        
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    try:
        # Save file temporarily
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Process and ingest to Vector DB
        ingest_file(
            tenant_id=current_user.company_id, 
            file_path=file_path, 
            filename=file.filename,
            source_type=source_type
        )
        return {"status": "success", "message": f"Successfully processed {file.filename}"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")
    finally:
        # Cleanup temporary file
        if os.path.exists(file_path):
            os.remove(file_path)

@router.get("")
def list_documents(current_user: User = Depends(get_current_user)):
    """Returns a list of documents in the company's knowledge base."""
    try:
        files = get_uploaded_files(current_user.company_id)
        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{filename}")
def remove_document(filename: str, current_user: User = Depends(get_current_user)):
    """Removes a document from the company's knowledge base."""
    if current_user.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can modify knowledge base.")
        
    try:
        delete_file(current_user.company_id, filename)
        return {"status": "success", "message": f"Deleted {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

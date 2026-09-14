import os
from typing import List
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_postgres import PGVector
from langchain_core.documents import Document
from src.rag.embeddings import get_embeddings
from src.config import get_settings

def get_vector_store() -> PGVector:
    """Initialize and return the PGVector store instance."""
    settings = get_settings()
    db_url = settings.database_url
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    return PGVector(
        embeddings=get_embeddings(),
        collection_name="tenant_knowledge",
        connection=db_url,
        use_jsonb=True,
    )

def ingest_file(tenant_id: str, file_path: str, filename: str, source_type: str = "company_policy"):
    """Loads a file, chunks it, and stores it in the vector database with the tenant_id and source_type."""
    
    # Load Document
    if file_path.lower().endswith('.pdf'):
        loader = PyPDFLoader(file_path)
        docs = loader.load()
    else:
        # Fallback to TextLoader for TXT or Markdown
        loader = TextLoader(file_path, encoding='utf-8')
        docs = loader.load()
        
    # Chunking
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    splits = text_splitter.split_documents(docs)
    
    # Inject metadata for Multi-Tenant Isolation
    for split in splits:
        split.metadata["tenant_id"] = tenant_id
        split.metadata["filename"] = filename
        split.metadata["source_type"] = source_type
        
    # Store in PGVector
    vector_store = get_vector_store()
    vector_store.add_documents(splits)
    
def retrieve_context(tenant_id: str, query: str, source_type: str = "company_policy", top_k: int = 4) -> str:
    """Retrieves relevant chunks strictly filtered by tenant_id and source_type."""
    vector_store = get_vector_store()
    
    # Filter by tenant_id and source_type
    retriever = vector_store.as_retriever(
        search_kwargs={
            "k": top_k,
            "filter": {"tenant_id": tenant_id, "source_type": source_type}
        }
    )
    
    docs = retriever.invoke(query)
    
    if not docs:
        return ""
        
    context = "\n\n".join([f"Fragmento ({doc.metadata.get('filename')}):\n{doc.page_content}" for doc in docs])
    return context
    
def get_uploaded_files(tenant_id: str) -> List[dict]:
    """Returns a list of files with their source_type uploaded by the tenant."""
    # Since PGVector in langchain doesn't easily expose distinct metadata via the high-level API,
    # we can do a generic similarity search with a blank query to get recent docs, or ideally
    # query the database directly. For simplicity, we will query via SQLAlchemy.
    from sqlalchemy import text
    from src.db.database import engine
    with engine.connect() as conn:
        # Langchain-postgres uses `langchain_pg_embedding` table and stores metadata in `cmetadata`
        try:
            query = text("""
                SELECT DISTINCT cmetadata->>'filename' as filename, cmetadata->>'source_type' as source_type
                FROM langchain_pg_embedding 
                WHERE cmetadata->>'tenant_id' = :tenant_id
                AND cmetadata->>'filename' IS NOT NULL
            """)
            result = conn.execute(query, {"tenant_id": tenant_id}).fetchall()
            return [{"filename": row[0], "source_type": row[1] or "company_policy"} for row in result if row[0]]
        except Exception as e:
            # Table might not exist yet if nothing was uploaded
            return []

def delete_file(tenant_id: str, filename: str):
    """Deletes all chunks associated with a specific file for a tenant."""
    from sqlalchemy import text
    from src.db.database import engine
    with engine.connect() as conn:
        query = text("""
            DELETE FROM langchain_pg_embedding 
            WHERE cmetadata->>'tenant_id' = :tenant_id
            AND cmetadata->>'filename' = :filename
        """)
        conn.execute(query, {"tenant_id": tenant_id, "filename": filename})
        conn.commit()

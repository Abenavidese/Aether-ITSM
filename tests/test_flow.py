import pytest
from fastapi.testclient import TestClient
import json
import os
import sqlite3

# Set up environment variables before importing app
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["DATABASE_URL"] = "sqlite:///./test_app.db"
os.environ["USE_OLLAMA"] = "True"
os.environ["OLLAMA_MODEL"] = "llama3.1"
os.environ["CHECKPOINT_DB_PATH"] = "test_checkpoints.db"

from src.main import app

client = TestClient(app)

def load_test_tickets():
    """Loads the synthetic tickets from our JSON file."""
    with open("tests/data/tickets.json", "r") as f:
        return json.load(f)

@pytest.fixture(autouse=True)
def setup_teardown():
    # Setup: Ensure test databases are clean
    if os.path.exists("test_app.db"):
        os.remove("test_app.db")
    if os.path.exists("test_checkpoints.db"):
        os.remove("test_checkpoints.db")
    
    # We must seed the test database first if there is logic depending on it
    # Currently tests just check webhooks, but this sets us up for future tests
    
    yield
    
    # Teardown
    if os.path.exists("test_app.db"):
        os.remove("test_app.db")
    if os.path.exists("test_checkpoints.db"):
        os.remove("test_checkpoints.db")

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_webhook_receives_tickets():
    tickets = load_test_tickets()
    
    for ticket in tickets:
        response = client.post("/api/webhook/ticket", json=ticket)
        assert response.status_code == 202
        assert response.json()["ticket_id"] == ticket["ticket_id"]
        assert response.json()["status"] == "Accepted"

def test_approve_ticket_not_found():
    # Since we are using TestClient which is synchronous and we don't await the background tasks,
    # the graph won't be fully executed to reach the paused state in a simple synchronous test flow.
    # Therefore, trying to approve immediately will return 404
    approval_payload = {
        "approved": True,
        "approver_id": "admin.smith"
    }
    
    response = client.post("/api/approve/IT-103", json=approval_payload)
    assert response.status_code == 404

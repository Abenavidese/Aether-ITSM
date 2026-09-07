import json
import time
import requests

# FastAPI Server URL
BASE_URL = "http://localhost:8000"

def load_test_tickets():
    """Loads the synthetic tickets from our JSON file."""
    with open("tests/data/tickets.json", "r") as f:
        return json.load(f)

def run_simulation():
    print("==================================================")
    print(" Aether ITSM - Backend End-to-End Simulation")
    print("==================================================")
    
    tickets = load_test_tickets()
    
    # 1. Send all tickets to the webhook
    for ticket in tickets:
        print(f"\n[TEST] Sending Ticket {ticket['ticket_id']} - {ticket['summary']}")
        try:
            response = requests.post(f"{BASE_URL}/api/webhook/ticket", json=ticket)
            print(f"[TEST] Webhook Response: {response.status_code} - {response.json()}")
        except requests.exceptions.ConnectionError:
            print("[TEST ERROR] FastAPI server is not running. Please start it with 'uvicorn src.main:app --reload'")
            return
            
        # Jitter to avoid SQLite locking issues as defined in our ADR/Metrics plan
        time.sleep(2)
        
    print("\n[TEST] All tickets sent. Waiting for LangGraph background tasks to reach checkpoints...")
    time.sleep(5) # Wait for LangGraph to reach the pause state for Risk 3
    
    # 2. Simulate Human IT Agent approving the Risk 3 Ticket (IT-103)
    print("\n[TEST] Simulating IT Agent Approval for Risk 3 Ticket (IT-103)")
    approval_payload = {
        "approved": True,
        "approver_id": "admin.smith"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/approve/IT-103", json=approval_payload)
        print(f"[TEST] Approval Response: {response.status_code} - {response.json()}")
    except Exception as e:
        print(f"[TEST ERROR] Failed to approve ticket: {e}")
        
    print("\n==================================================")
    print(" Simulation Complete! Check the FastAPI console logs")
    print("==================================================")

if __name__ == "__main__":
    run_simulation()

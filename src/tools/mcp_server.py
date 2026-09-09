import json
import logging
from mcp.server.fastmcp import FastMCP
from src.config import get_settings

logger = logging.getLogger(__name__)

# Create the MCP Server instance
mcp = FastMCP("Aether_ITSM_Server")

# ---------------------------------------------------------
# MCP Tools Definition (Exposed over stdio)
# ---------------------------------------------------------

@mcp.tool()
def reset_vpn_session(user_id: str) -> str:
    """
    Terminates active VPN sessions for a specific user to fix hung connections.
    Risk Level: 2
    """
    logger.info("Executing reset_vpn_session for %s", user_id)
    result = {
        "status": "success",
        "action": "vpn_session_terminated",
        "user_id": user_id,
        "message": f"Active VPN sessions for {user_id} have been cleared."
    }
    return json.dumps(result)

@mcp.tool()
def provision_standard_software(user_id: str, software_id: str) -> str:
    """
    Adds a user to an AD group that triggers an automated MDM software install.
    Risk Level: 2
    """
    logger.info("Provisioning %s for %s", software_id, user_id)
    settings = get_settings()
    whitelist = settings.get_mdm_whitelist_list
    
    if software_id not in whitelist:
        return json.dumps({
            "status": "error",
            "message": f"Software {software_id} is not in the standard whitelist. Manual approval required."
        })
        
    return json.dumps({
        "status": "success",
        "action": "mdm_group_added",
        "user_id": user_id,
        "software_id": software_id,
        "message": f"User {user_id} added to MDM deployment group for {software_id}."
    })

@mcp.tool()
def modify_iam_access(user_id: str, resource_arn: str, access_level: str) -> str:
    """
    Modifies cloud or directory access policies.
    Risk Level: 3 (Requires Approval before invocation)
    """
    logger.info("Modifying IAM Access: %s -> %s (%s)", user_id, resource_arn, access_level)
    return json.dumps({
        "status": "success",
        "action": "iam_policy_attached",
        "user_id": user_id,
        "resource": resource_arn,
        "level": access_level,
        "message": f"Successfully granted {access_level} to {user_id} on {resource_arn}."
    })

@mcp.tool()
def query_knowledge_base(query_string: str) -> str:
    """
    Performs a semantic search over internal Tier 1 support documentation.
    Risk Level: 0
    """
    logger.info("Querying KB for: %s", query_string)
    # In a real app, this would query a Vector DB.
    # For now, returning standard simulated responses.
    return json.dumps({
        "status": "success",
        "results": [
            "VPN issues are typically resolved by terminating the active session.",
            "Docker Desktop requires the user to be in the `pkg_docker` MDM group."
        ]
    })

if __name__ == "__main__":
    # Start the server using standard IO transport (expected by MCP Clients)
    mcp.run(transport="stdio")

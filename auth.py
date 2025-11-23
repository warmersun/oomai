import chainlit as cl
from typing import Optional, Dict


# @cl.password_auth_callback
# def auth_callback(username: str, password: str) -> Optional[cl.User]:
#     if (username, password) == ("Sic", "kadima"):
#         return cl.User(identifier="Sic",
#                        metadata={
#                            "role": "admin",
#                            "provider": "credentials"
#                        })
#     elif (username, password) == ("User", "oom.today"):
#         return cl.User(identifier=username,
#                        metadata={
#                            "role": "user",
#                            "provider": "credentials"
#                        })
#     else:
#         return None

@cl.oauth_callback
def oauth_callback(
    provider_id: str,
    token: str,
    raw_user_data: Dict[str, str],
    default_user: cl.User,
) -> Optional[cl.User]:
    logger.info(f"OAuth callback: {provider_id}, {token}, {raw_user_data}")
    assert DESCOPE_PROJECT_ID is not None, "DESCOPE_PROJECT_ID is not set"
    descope_client = DescopeClient(project_id=DESCOPE_PROJECT_ID)
    roles = [
        "admin",
    ]
    try:
        jwt_response = descope_client.validate_session(
            session_token=token, audience=DESCOPE_PROJECT_ID)
        is_admin_role = descope_client.validate_roles(jwt_response, roles)
        logger.info(f"Is admin role?: {is_admin_role}")
        if is_admin_role:
            default_user.metadata["role"] = "admin"
    except Exception as error:
        logger.error(f"Error getting matched roles: {error}")
    finally:
        return default_user

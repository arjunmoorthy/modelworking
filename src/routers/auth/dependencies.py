import os
import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import BaseModel
import logging
import boto3

# This will require the client to send a header: "Authorization: Bearer <token>"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Configure logging
logger = logging.getLogger(__name__)

# --- Pydantic Models ---
class TokenData(BaseModel):
    sub: str  # The unique user ID from Cognito
    email: str | None = None
    
# --- Cognito JWKS Caching ---
_jwks_cache = {}

def _get_jwks():
    """
    Fetches and caches the JSON Web Key Set (JWKS) from Cognito.
    The JWKS contains the public keys used to verify JWTs.
    """
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache

    region = os.getenv("AWS_REGION")
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
    jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
    
    try:
        response = requests.get(jwks_url)
        response.raise_for_status()
        _jwks_cache = response.json()
        return _jwks_cache
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch JWKS from {jwks_url}: {e}")
        raise HTTPException(status_code=500, detail="Could not fetch security keys.")

def get_cognito_client():
    """Get AWS Cognito client, reusable across routers."""
    return boto3.client(
        "cognito-idp",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

# --- The Main Security Dependency ---
async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    """
    Validates the Cognito JWT token and returns the user's data.
    This is the dependency that will protect our routes.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        jwks = _get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"]
                }
        if not rsa_key:
            logger.error("Unable to find a matching public key.")
            raise credentials_exception

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=os.getenv("COGNITO_CLIENT_ID"),
            issuer=f"https://cognito-idp.{os.getenv('AWS_REGION')}.amazonaws.com/{os.getenv('COGNITO_USER_POOL_ID')}"
        )
        
        # The 'sub' claim is the user's unique ID.
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
            
        return TokenData(sub=user_id, email=payload.get("email"))

    except JWTError as e:
        logger.error(f"JWT validation error: {e}")
        raise credentials_exception
    except Exception as e:
        logger.error(f"An unexpected error occurred during token validation: {e}")
        raise credentials_exception 
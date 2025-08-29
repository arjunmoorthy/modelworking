"""
Authentication Routes

This module provides authentication endpoints using AWS Cognito:

Routes:
- POST /auth/signup: Register a new user account with email, first name, and last name
- POST /auth/login: Authenticate user with email/password and return JWT tokens
- POST /auth/complete-new-password: Complete password setup for users with temporary passwords
- POST /auth/forgot-password: Send password reset code to user's email
- POST /auth/reset-password: Reset password using confirmation code from email
- POST /auth/logout: Client-side logout (formality endpoint)
- DELETE /auth/delete-patient: Delete patient account and all associated data (testing only)

All routes handle Cognito integration and manage user data in the patient database.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
import boto3
from botocore.exceptions import ClientError
import logging
import hmac
import hashlib
import base64
from pydantic import BaseModel
from uuid import UUID

# Use absolute imports from the 'backend' directory
from routers.auth.models import (
    SignupRequest,
    SignupResponse,
    LoginRequest,
    LoginResponse,
    CompleteNewPasswordRequest,
    CompleteNewPasswordResponse,
    AuthTokens,
    DeletePatientRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
# Import DB session and models
from db.database import get_patient_db, get_doctor_db
from db.patient_models import (
    PatientInfo,
    PatientConfigurations,
    PatientDiaryEntries,
    Conversations,
    PatientChemoDates,
    PatientPhysicianAssociations
)
from db.doctor_models import StaffProfiles
# Import shared dependencies
from routers.auth.dependencies import get_cognito_client, get_current_user, TokenData


class LogoutResponse(BaseModel):
    message: str


# Load environment variables
load_dotenv()

# Create router
router = APIRouter(prefix="/auth", tags=["authentication"])

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_secret_hash(username: str, client_id: str, client_secret: str) -> str:
    """Calculates the SecretHash for Cognito API calls."""
    msg = username + client_id
    dig = hmac.new(
        key=client_secret.encode("utf-8"),
        msg=msg.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(dig).decode()


@router.post("/logout", response_model=LogoutResponse)
async def logout():
    """
    Client-side logout. The real action is the client deleting the token.
    This endpoint is a formality.
    """
    logger.info("[AUTH] /logout called")
    return {"message": "Logout successful"}


@router.post("/signup", response_model=SignupResponse)
async def signup_user(
    request: SignupRequest,
    patient_db: Session = Depends(get_patient_db),
    doctor_db: Session = Depends(get_doctor_db)
):
    """
    Create a new user in AWS Cognito User Pool.
    On success, also creates corresponding records in the patient_info
    and patient_configurations tables.
    If a physician_email is provided, it links the patient to the physician.
    """
    logger.info(f"[AUTH] /signup email={request.email} physician_email={getattr(request, 'physician_email', None)}")
    # Check if a non-deleted user with this email already exists in the local DB
    existing_patient = patient_db.query(PatientInfo).filter(
        PatientInfo.email_address == request.email,
        PatientInfo.is_deleted == False
    ).first()

    if existing_patient:
        logger.warning(f"[AUTH] /signup conflict email={request.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A user with email {request.email} already exists and is active."
        )

    try:
        user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
        if not user_pool_id:
            logger.error("[AUTH] /signup missing COGNITO_USER_POOL_ID")
            raise HTTPException(
                status_code=500, detail="COGNITO_USER_POOL_ID not configured"
            )

        cognito_client = get_cognito_client()

        user_attributes = [
            {"Name": "email", "Value": request.email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "given_name", "Value": request.first_name},
            {"Name": "family_name", "Value": request.last_name},
        ]

        response = cognito_client.admin_create_user(
            UserPoolId=user_pool_id,
            Username=request.email,
            UserAttributes=user_attributes,
            ForceAliasCreation=False,
        )
        logger.info(f"[AUTH] /signup created in Cognito email={request.email}")

        # Extract the UUID (sub) that Cognito automatically generates
        user_sub = None
        for attribute in response["User"]["Attributes"]:
            if attribute["Name"] == "sub":
                user_sub = attribute["Value"]
                break
        
        if not user_sub:
            logger.error(f"[AUTH] /signup missing sub in Cognito response email={request.email}")
            raise HTTPException(status_code=500, detail="User created in Cognito, but failed to retrieve UUID.")

        logger.info(
            f"[AUTH] /signup success email={request.email} uuid={user_sub}"
        )

        # Now, create the corresponding records in our own database
        new_patient_info = PatientInfo(
            uuid=user_sub,
            email_address=request.email,
            first_name=request.first_name,
            last_name=request.last_name,
        )
        new_patient_config = PatientConfigurations(uuid=user_sub)

        patient_db.add(new_patient_info)
        patient_db.add(new_patient_config)

        # Step 3: Associate a physician for all new patients
        # Prefer the physician by email if provided; otherwise use the default UUID
        default_physician_uuid = 'bea3fce0-42f9-4a00-ae56-4e2591ca17c5'
        default_clinic_uuid = 'ab4dac8e-f9dc-4399-b9bd-781a9d540139'
        associated_physician_uuid = None

        if request.physician_email:
            physician_profile = doctor_db.query(StaffProfiles).filter(
                StaffProfiles.email_address == request.physician_email,
                StaffProfiles.role == 'physician'
            ).first()

            if physician_profile:
                associated_physician_uuid = physician_profile.staff_uuid
            else:
                logger.warning(
                    f"[AUTH] /signup physician email not found '{request.physician_email}', falling back to default physician"
                )

        if not associated_physician_uuid:
            associated_physician_uuid = default_physician_uuid

        new_association = PatientPhysicianAssociations(
            patient_uuid=user_sub,
            physician_uuid=associated_physician_uuid,
            clinic_uuid=default_clinic_uuid
        )
        patient_db.add(new_association)
        
        patient_db.commit()
        logger.info(f"[AUTH] /signup DB records created uuid={user_sub}")

        return SignupResponse(
            message=f"User {request.email} created successfully. A temporary password has been sent to their email.",
            email=request.email,
            user_status=response["User"]["UserStatus"],
        )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        logger.error(f"[AUTH] /signup Cognito error code={error_code} message='{error_message}' email={request.email}")
        raise HTTPException(
            status_code=500, detail=f"AWS Cognito error: {error_message}"
        )
    except Exception as e:
        logger.error(f"[AUTH] /signup unexpected error email={request.email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/login", response_model=LoginResponse)
async def validate_login(request: LoginRequest):
    """
    Validate if a user's email and password is valid for login.
    If a temporary password is used, it returns a session token for the password change flow.
    """
    logger.info(f"[AUTH] /login email={request.email}")
    try:
        user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
        client_id = os.getenv("COGNITO_CLIENT_ID")
        client_secret = os.getenv("COGNITO_CLIENT_SECRET")

        if not user_pool_id or not client_id:
            logger.error("[AUTH] /login missing Cognito envs")
            raise HTTPException(
                status_code=500,
                detail="COGNITO_USER_POOL_ID or COGNITO_CLIENT_ID not configured",
            )

        cognito_client = get_cognito_client()

        auth_parameters = {"USERNAME": request.email, "PASSWORD": request.password}

        if client_secret:
            auth_parameters["SECRET_HASH"] = _get_secret_hash(
                request.email, client_id, client_secret
            )

        auth_response = cognito_client.admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters=auth_parameters,
        )

        logger.info(f"[AUTH] /login Cognito response keys={list(auth_response.keys())}")

        if "AuthenticationResult" in auth_response:
            logger.info(f"[AUTH] /login success email={request.email}")
            auth_result = auth_response["AuthenticationResult"]
            tokens = AuthTokens(
                access_token=auth_result["AccessToken"],
                refresh_token=auth_result["RefreshToken"],
                id_token=auth_result["IdToken"],
                token_type=auth_result["TokenType"],
            )
            return LoginResponse(
                valid=True,
                message="Login credentials are valid",
                user_status="CONFIRMED",
                tokens=tokens
            )

        elif "ChallengeName" in auth_response:
            challenge_name = auth_response["ChallengeName"]
            session = auth_response.get("Session")
            logger.info(f"[AUTH] /login challenge email={request.email} name={challenge_name}")

            if challenge_name == "NEW_PASSWORD_REQUIRED":
                return LoginResponse(
                    valid=True,
                    message="Login credentials are valid but password change is required.",
                    user_status="FORCE_CHANGE_PASSWORD",
                    session=session,
                )
            else:
                return LoginResponse(
                    valid=True,
                    message=f"Login credentials are valid but challenge required: {challenge_name}",
                    user_status="CHALLENGE_REQUIRED",
                    session=session,
                )
        else:
            logger.warning(f"[AUTH] /login unexpected response email={request.email}")
            return LoginResponse(valid=False, message="Unexpected authentication response")

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        logger.error(f"[AUTH] /login Cognito error email={request.email} code={error_code} msg='{error_message}'")
        if error_code == "NotAuthorizedException":
            return LoginResponse(valid=False, message="Invalid email or password")
        elif error_code == "UserNotFoundException":
            return LoginResponse(valid=False, message="User not found")
        else:
            raise HTTPException(
                status_code=500, detail=f"AWS Cognito error: {error_message}"
            )
    except Exception as e:
        logger.error(f"[AUTH] /login unexpected error email={request.email}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/complete-new-password", response_model=CompleteNewPasswordResponse)
async def complete_new_password(request: CompleteNewPasswordRequest):
    """
    Complete the new password setup for a user who was created with a temporary password.
    """
    logger.info(f"[AUTH] /complete-new-password email={request.email}")
    try:
        user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
        client_id = os.getenv("COGNITO_CLIENT_ID")
        client_secret = os.getenv("COGNITO_CLIENT_SECRET")

        if not user_pool_id or not client_id:
            logger.error("[AUTH] /complete-new-password missing Cognito envs")
            raise HTTPException(
                status_code=500,
                detail="COGNITO_USER_POOL_ID or COGNITO_CLIENT_ID not configured",
            )

        cognito_client = get_cognito_client()

        challenge_responses = {
            "USERNAME": request.email,
            "NEW_PASSWORD": request.new_password,
        }

        if client_secret:
            challenge_responses["SECRET_HASH"] = _get_secret_hash(
                request.email, client_id, client_secret
            )

        response = cognito_client.admin_respond_to_auth_challenge(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            ChallengeName="NEW_PASSWORD_REQUIRED",
            Session=request.session,
            ChallengeResponses=challenge_responses,
        )

        if "AuthenticationResult" in response:
            logger.info(f"[AUTH] /complete-new-password success email={request.email}")
            auth_result = response["AuthenticationResult"]
            tokens = AuthTokens(
                access_token=auth_result["AccessToken"],
                refresh_token=auth_result["RefreshToken"],
                id_token=auth_result["IdToken"],
                token_type=auth_result["TokenType"],
            )
            return CompleteNewPasswordResponse(
                message="Password successfully changed and user authenticated.",
                tokens=tokens,
            )
        else:
            logger.error(f"[AUTH] /complete-new-password unexpected response email={request.email}")
            raise HTTPException(
                status_code=400,
                detail="Could not set new password. Unexpected response from authentication service.",
            )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        logger.error(
            f"[AUTH] /complete-new-password Cognito error email={request.email} code={error_code} msg='{error_message}'"
        )
        if error_code in [
            "NotAuthorizedException",
            "CodeMismatchException",
            "ExpiredCodeException",
        ]:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired session. Please try logging in again.",
            )
        if error_code == "InvalidPasswordException":
            raise HTTPException(
                status_code=400,
                detail=f"New password does not meet requirements: {error_message}",
            )
        raise HTTPException(
            status_code=500, detail=f"AWS Cognito error: {error_message}"
        )

    except Exception as e:
        logger.error(
            f"[AUTH] /complete-new-password unexpected error email={request.email}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(request: ForgotPasswordRequest):
    """
    Send a password reset code to the user's email via AWS Cognito.
    This initiates the password reset flow.
    """
    logger.info(f"[AUTH] /forgot-password email={request.email}")
    try:
        client_id = os.getenv("COGNITO_CLIENT_ID")
        client_secret = os.getenv("COGNITO_CLIENT_SECRET")

        if not client_id:
            logger.error("[AUTH] /forgot-password missing COGNITO_CLIENT_ID")
            raise HTTPException(
                status_code=500,
                detail="COGNITO_CLIENT_ID not configured",
            )

        cognito_client = get_cognito_client()

        # Prepare the request parameters
        params = {
            "ClientId": client_id,
            "Username": request.email,
        }

        # Add SecretHash if client secret is configured
        if client_secret:
            params["SecretHash"] = _get_secret_hash(
                request.email, client_id, client_secret
            )

        # Initiate the forgot password flow
        cognito_client.forgot_password(**params)

        logger.info(f"[AUTH] /forgot-password success email={request.email}")
        return ForgotPasswordResponse(
            message="Password reset code sent to your email address",
            email=request.email
        )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        logger.error(f"[AUTH] /forgot-password Cognito error email={request.email} code={error_code} msg='{error_message}'")

        if error_code == "UserNotFoundException":
            # For security, we don't reveal if the user exists or not
            logger.info(f"[AUTH] /forgot-password user not found email={request.email}")
            return ForgotPasswordResponse(
                message="If an account with this email exists, a password reset code has been sent",
                email=request.email
            )
        elif error_code == "LimitExceededException":
            raise HTTPException(
                status_code=429,
                detail="Too many password reset attempts. Please wait before trying again."
            )
        else:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to initiate password reset: {error_message}"
            )

    except Exception as e:
        logger.error(f"[AUTH] /forgot-password unexpected error email={request.email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(request: ResetPasswordRequest):
    """
    Reset the user's password using the confirmation code sent to their email.
    This completes the password reset flow initiated by forgot-password.
    """
    logger.info(f"[AUTH] /reset-password email={request.email}")
    try:
        client_id = os.getenv("COGNITO_CLIENT_ID")
        client_secret = os.getenv("COGNITO_CLIENT_SECRET")

        if not client_id:
            logger.error("[AUTH] /reset-password missing COGNITO_CLIENT_ID")
            raise HTTPException(
                status_code=500,
                detail="COGNITO_CLIENT_ID not configured",
            )

        cognito_client = get_cognito_client()

        # Prepare the request parameters
        params = {
            "ClientId": client_id,
            "Username": request.email,
            "ConfirmationCode": request.confirmation_code,
            "Password": request.new_password,
        }

        # Add SecretHash if client secret is configured
        if client_secret:
            params["SecretHash"] = _get_secret_hash(
                request.email, client_id, client_secret
            )

        # Confirm the password reset
        cognito_client.confirm_forgot_password(**params)

        logger.info(f"[AUTH] /reset-password success email={request.email}")
        return ResetPasswordResponse(
            message="Password has been successfully reset. You can now log in with your new password.",
            email=request.email
        )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        logger.error(f"[AUTH] /reset-password Cognito error email={request.email} code={error_code} msg='{error_message}'")

        if error_code == "CodeMismatchException":
            raise HTTPException(
                status_code=400,
                detail="Invalid confirmation code. Please check the code and try again."
            )
        elif error_code == "ExpiredCodeException":
            raise HTTPException(
                status_code=400,
                detail="Confirmation code has expired. Please request a new password reset."
            )
        elif error_code == "UserNotFoundException":
            raise HTTPException(
                status_code=404,
                detail="User not found."
            )
        elif error_code == "InvalidPasswordException":
            raise HTTPException(
                status_code=400,
                detail=f"New password does not meet requirements: {error_message}"
            )
        elif error_code == "LimitExceededException":
            raise HTTPException(
                status_code=429,
                detail="Too many password reset attempts. Please wait before trying again."
            )
        else:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to reset password: {error_message}"
            )

    except Exception as e:
        logger.error(f"[AUTH] /reset-password unexpected error email={request.email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/delete-patient", status_code=status.HTTP_204_NO_CONTENT, summary="Delete patient account")
async def delete_patient(
    request: DeletePatientRequest,
    db: Session = Depends(get_patient_db)
):
    """
    Deletes all data for the specified user from the application database.
    Can delete by email or UUID. Optionally skips AWS Cognito deletion.
    This is an irreversible action.
    """
    # Validate that either email or UUID is provided
    if not request.email and not request.uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either email or uuid must be provided"
        )
    
    # Find the user by email or UUID
    patient_info = None
    if request.uuid:
        try:
            patient_uuid = UUID(request.uuid)
            patient_info = db.query(PatientInfo).filter(PatientInfo.uuid == patient_uuid).first()
            logger.warning(f"[AUTH] /delete-patient start uuid={request.uuid}")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid UUID format"
            )
    else:
        patient_info = db.query(PatientInfo).filter(PatientInfo.email_address == request.email).first()
        logger.warning(f"[AUTH] /delete-patient start email={request.email}")
    
    if not patient_info:
        identifier = request.uuid or request.email
        logger.error(f"[AUTH] /delete-patient patient not found identifier={identifier}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Patient not found with identifier: {identifier}"
        )
    
    user_id = patient_info.uuid
    user_email = patient_info.email_address
    logger.warning(f"[AUTH] /delete-patient deleting uuid={user_id} email={user_email}")

    # --- Step 1: Soft-delete all related data in the database ---
    try:
        # Soft delete all patient-related records
        db.query(PatientDiaryEntries).filter(PatientDiaryEntries.patient_uuid == user_id).update({"is_deleted": True})
        db.query(PatientPhysicianAssociations).filter(PatientPhysicianAssociations.patient_uuid == user_id).update({"is_deleted": True})
        db.query(PatientConfigurations).filter(PatientConfigurations.uuid == user_id).update({"is_deleted": True})
        db.query(PatientInfo).filter(PatientInfo.uuid == user_id).update({"is_deleted": True})
        logger.info(f"Database records processed for user {user_id}")
    except Exception as e:
        db.rollback()
        logger.error(f"[AUTH] /delete-patient DB cleanup failed uuid={user_id} error={e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete user data. Please try again.")

    # --- Step 2: Delete the user from Cognito (unless skipped) ---
    if not request.skip_aws:
        try:
            cognito_client = get_cognito_client()
            cognito_client.admin_delete_user(
                UserPoolId=os.getenv("COGNITO_USER_POOL_ID"),
                Username=user_email
            )
            logger.info(f"[AUTH] /delete-patient deleted from Cognito uuid={user_id}")
        except ClientError as e:
            db.rollback()
            logger.error(f"[AUTH] /delete-patient Cognito delete failed uuid={user_id} error={e.response['Error']['Message']}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete user from authentication service.")
    else:
        logger.info(f"[AUTH] /delete-patient skipped AWS Cognito deletion uuid={user_id}")
    
    # --- Step 3: Commit the transaction ---
    db.commit()
    logger.warning(f"[AUTH] /delete-patient complete uuid={user_id} email={user_email}")
    
    return
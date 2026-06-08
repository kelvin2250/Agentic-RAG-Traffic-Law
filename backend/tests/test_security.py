import pytest
from datetime import timedelta
from app.core.security import get_password_hash, verify_password, create_access_token, decode_token

def test_password_hashing_and_verification():
    """Test that password hashing and verification works correctly."""
    password = "secure_test_password_123"
    hashed = get_password_hash(password)
    
    # The hash should not be equal to the plain password
    assert hashed != password
    
    # Verification of the correct password should succeed
    assert verify_password(password, hashed) is True
    
    # Verification of a wrong password should fail
    assert verify_password("wrong_password", hashed) is False

def test_jwt_token_creation_and_decoding():
    """Test that JWT access tokens can be created and decoded correctly."""
    subject = "test_user_id_999"
    
    # Create an access token
    token = create_access_token(subject=subject, expires_delta=timedelta(minutes=10))
    assert isinstance(token, str)
    assert len(token) > 0
    
    # Decode and verify the token
    decoded = decode_token(token)
    assert decoded is not None
    assert decoded["sub"] == subject
    assert decoded["type"] == "access"
    
    # Decoding an invalid token should return None
    assert decode_token("invalid.token.structure") is None

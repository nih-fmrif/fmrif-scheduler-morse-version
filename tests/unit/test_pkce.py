import re

from scheduler.auth.pkce import code_challenge_s256, generate_code_verifier


def test_generate_code_verifier_format():
    verifier = generate_code_verifier()
    assert 43 <= len(verifier) <= 128
    assert re.fullmatch(r"[A-Za-z0-9_-]+", verifier)


def test_code_challenge_matches_rfc7636_vector():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected_challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert code_challenge_s256(verifier) == expected_challenge

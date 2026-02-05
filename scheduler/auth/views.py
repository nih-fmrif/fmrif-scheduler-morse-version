"""Authentication views"""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from .jwt_utils import extract_bearer_token
from .session import login_user_with_token, logout_user

# Create blueprint
auth = Blueprint("auth", __name__)


@auth.route("/login", methods=["GET"])
def login():
    """Render OAuth login page (frontend handles redirect)."""
    return render_template("auth/login.html")


@auth.route("/callback")
def callback():
    """Handle OAuth redirect from Microsoft Entra.

    Entra redirects here with ?code=xxx&state=yyy after user authentication.
    The page renders login.html; the JavaScript on that page detects the
    code parameter, exchanges it for tokens via PKCE, then establishes
    a server session via POST /auth/session.
    """
    return render_template("auth/login.html")


@auth.route("/session", methods=["POST"])
def establish_session():
    """Create a server session from a validated JWT bearer token."""
    token = extract_bearer_token(request.headers.get("Authorization"))
    if not token:
        return jsonify({"error": "Missing bearer token"}), 401

    user = login_user_with_token(token)
    if not user:
        return jsonify({"error": "Invalid or expired token"}), 401

    return jsonify({"email": user.email, "username": user.username})


@auth.route("/logout")
def logout():
    """Handle user logout"""
    logout_user()
    flash("Successfully logged out", "success")
    return redirect(url_for("home"))

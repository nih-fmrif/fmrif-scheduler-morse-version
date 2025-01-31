# tests/python/test_auth.py
import pytest
from scheduler import logic
from scheduler.app import login_required, admin_only
from flask import g

def test_superuser_creation(app_context):
    superuser = logic.get_or_create_superuser()
    assert superuser.id == "superuser"
    assert superuser.label == "Superuser"
    assert superuser.addr == "superuser@example.com"
    assert superuser.active is True

def test_login_required(app, client):
    @app.route('/protected')
    @login_required 
    def protected():
        return 'protected'
        
    with app.test_request_context():
        g.user = None
        response = client.get('/protected')
        assert response.status_code == 403

def test_admin_only(app, client):
    @app.route('/admin')
    @admin_only
    def admin():
        return 'admin only'
        
    with app.test_request_context():
        g.user = None
        response = client.get('/admin')
        assert response.status_code == 403

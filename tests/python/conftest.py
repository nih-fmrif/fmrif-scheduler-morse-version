# tests/python/conftest.py
import pytest
from flask import Flask
from scheduler.config import settings, app_config
from scheduler import model
from sqlalchemy import text

@pytest.fixture
def app():
    app = Flask(__name__)
    # Override database host for tests
    test_config = dict(app_config)
    test_config['SQLALCHEMY_DATABASE_URI'] = test_config['SQLALCHEMY_DATABASE_URI'].replace('postgres:5432', 'localhost:5050')
    test_config['SERVER_NAME'] = 'localhost.localdomain:5051'  # Use localhost.localdomain instead of localhost
    app.config.update(**test_config)
    model.db.init_app(app)
    return app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def runner(app):
    return app.test_cli_runner()

@pytest.fixture
def app_context(app):
    with app.app_context():
        model.db.create_all()
        yield app
        model.db.session.remove()
        # Drop tables with CASCADE
        model.db.session.execute(text('DROP SCHEMA public CASCADE'))
        model.db.session.execute(text('CREATE SCHEMA public'))
        model.db.session.commit()

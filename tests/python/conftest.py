import pytest
from flask import Flask
from scheduler.config import settings, app_config
from scheduler import model

@pytest.fixture
def app():
    app = Flask(__name__)
    app.config.update(**app_config)
    model.db.init_app(app)
    return app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def runner(app):
    return app.test_cli_runner() 
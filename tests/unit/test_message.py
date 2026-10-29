from smtplib import SMTPException

from flask import Flask

from scheduler import message


def _mail_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        MAIL_DEFAULT_SENDER="noreply@example.com",
        MAIL_SUPPRESS_SEND=False,
    )
    message.mailer.init_app(app)
    return app


def test_send_returns_false_on_socket_error(monkeypatch):
    app = _mail_app()
    with app.app_context():
        monkeypatch.setattr(
            message.mailer,
            "send",
            lambda _m: (_ for _ in ()).throw(ConnectionRefusedError("refused")),
        )
        assert message.send("to@example.com", "subject", "body") is False


def test_send_returns_false_on_smtp_exception(monkeypatch):
    app = _mail_app()
    with app.app_context():
        monkeypatch.setattr(
            message.mailer,
            "send",
            lambda _m: (_ for _ in ()).throw(SMTPException("smtp error")),
        )
        assert message.send("to@example.com", "subject", "body") is False


def test_send_uses_subject_and_recipients(monkeypatch):
    app = _mail_app()
    captured = {}

    def _capture_send(msg):
        captured["subject"] = msg.subject
        captured["recipients"] = msg.recipients

    with app.app_context():
        monkeypatch.setattr(message.mailer, "send", _capture_send)
        assert (
            message.send("a@example.com, b@example.com", "join request", "hello")
            is True
        )

    assert captured["subject"] == "join request"
    assert captured["recipients"] == ["a@example.com", "b@example.com"]

"""Explicit operational bootstrap commands; never run during application startup."""
import hmac
import os

import click
from sqlalchemy import select

from .auth import hash_password, normalize_email
from .database import db
from .models import AuditLog, Role, User


def register_commands(app):
    @app.cli.command("bootstrap-admin")
    @click.option("--email", required=True)
    @click.option("--password", required=True, hide_input=True)
    @click.option("--token", required=True, hide_input=True)
    def bootstrap_admin(email, password, token):
        """Create the first admin using a one-time deployment secret."""
        expected = os.environ.get("ADMIN_BOOTSTRAP_TOKEN", "")
        if len(expected) < 32 or not hmac.compare_digest(expected, token):
            raise click.ClickException("Bootstrap authorization failed")
        if db.session.scalar(select(User).join(Role).where(Role.code == "ADMIN")) is not None:
            raise click.ClickException("An administrator already exists; use controlled admin operations")
        roles = {}
        for code in ("PATIENT", "DOCTOR", "ADMIN"):
            role = db.session.scalar(select(Role).where(Role.code == code))
            if role is None:
                role = Role(code=code); db.session.add(role)
            roles[code] = role
        db.session.flush()
        user = User(normalized_email=normalize_email(email), password_hash=hash_password(password), role=roles["ADMIN"])
        db.session.add(user); db.session.flush()
        db.session.add(AuditLog(actor_id=user.id, event="ADMIN_BOOTSTRAPPED", resource_type="user",
                                resource_id=user.id, request_id="cli-bootstrap", safe_metadata={}))
        db.session.commit()
        click.echo(f"Administrator created: {user.id}")

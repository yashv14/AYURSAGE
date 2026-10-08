"""Safe errors and server-generated correlation IDs."""
from uuid import uuid4

from flask import g, jsonify
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import HTTPException

from .database import db



class ApiError(Exception):
    def __init__(self, code, message, status, fields=None):
        super().__init__(message)
        self.code, self.message, self.status, self.fields = code, message, status, fields


def error_response(code, message, status, fields=None):
    error = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return jsonify(error=error, requestId=g.request_id), status


def register_errors(app):
    @app.before_request
    def request_id():
        g.request_id = str(uuid4())

    @app.after_request
    def correlation_header(response):
        response.headers["X-Request-ID"] = g.request_id
        return response

    @app.errorhandler(ApiError)
    def api_error(error):
        db.session.rollback()
        return error_response(error.code, error.message, error.status, error.fields)

    @app.errorhandler(HTTPException)
    def http_error(error):
        return error_response(error.name.upper().replace(" ", "_"), error.name, error.code)

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        # PyMySQL maps MySQL CHECK violations to OperationalError, not IntegrityError.
        original_args = getattr(getattr(error, "orig", None), "args", ())
        if original_args and original_args[0] == 3819:
            return error_response("CONFLICT", "Operation conflicts with stored state", 409)
        app.logger.error("Database request failed request_id=%s", g.request_id)
        return error_response("DATABASE_UNAVAILABLE", "Database operation unavailable", 503)

    @app.errorhandler(IntegrityError)
    def integrity_error(error):
        db.session.rollback()
        return error_response("CONFLICT", "Operation conflicts with stored state", 409)

    @app.errorhandler(StaleDataError)
    def stale_error(error):
        db.session.rollback()
        return error_response("STALE_VERSION", "Resource has changed", 409)

    @app.errorhandler(Exception)
    def unexpected_error(error):
        db.session.rollback()
        app.logger.error("Request failed request_id=%s", g.request_id)
        return error_response("INTERNAL_ERROR", "Request could not be completed", 500)

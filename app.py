import json
import os
import sys

from dotenv import load_dotenv

from flask import Flask, request, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy

from loguru import logger
from loguru._defaults import LOGURU_ERROR_NO

from loki_logger_handler.formatters.loguru_formatter import LoguruFormatter
from loki_logger_handler.loki_logger_handler import LokiLoggerHandler

from prometheus_flask_exporter import PrometheusMetrics

from request_id import RequestId

from sqlalchemy.sql import text
from sqlalchemy.exc import OperationalError

"""Environment variables"""
load_dotenv()

DEBUG = os.getenv("DEBUG", "false").lower() == "true"

"""Structural logging"""
logger.remove(0)


def filter_to_stdout(record):
    return record['level'].no < LOGURU_ERROR_NO


def filter_to_stderr(record):
    return record['level'].no >= LOGURU_ERROR_NO


def serialize(record):
    subset = {
        'timestamp': record['time'].isoformat(),
        'level':     record['level'].name,
        'message':   record['message'],
    }

    extra_keys = [
        'ip_address', 'method', 'path', 'request_id',
        'user_id'
    ]

    for extra_key in extra_keys:
        if extra_key in record['extra'].keys():
            subset[extra_key] = record['extra'][extra_key]

    return json.dumps(subset)


def patching(record):
    record['extra']['serialized'] = serialize(record)


logger = logger.patch(patching)

# Console output
logger.add(
    sink=sys.stdout,
    level='DEBUG' if DEBUG else 'INFO',
    filter=filter_to_stdout,
    format='{extra[serialized]}',
)
logger.add(
    sink=sys.stderr,
    level='ERROR',
    filter=filter_to_stderr,
    format='{extra[serialized]}',
)

# File output
logger.add(
    sink='/var/log/flask_app_stdout.log',
    rotation='1 MB',
    level='DEBUG' if DEBUG else 'INFO',
    filter=filter_to_stdout,
    format='{extra[serialized]}',
)
logger.add(
    sink='/var/log/flask_app_stderr.log',
    rotation='1 MB',
    level='ERROR',
    filter=filter_to_stderr,
    format='{extra[serialized]}',
)

# Aggregation service output
class CustomLoguruFormatter(LoguruFormatter):
    def format(self, record):
        timestamp = record.get('time')
        if hasattr(timestamp, 'timestamp'):
            timestamp = timestamp.isoformat()

        formatted = {
            'timestamp': timestamp,
            'level': record.get('level').name.upper(),
            'message': record.get('message'),
        }

        loki_metadata = {}

        extra = record.get('extra', {})
        if isinstance(extra, dict):
            if 'extra' in extra and isinstance(extra['extra'], dict):
                formatted.update(extra['extra'])
            else:
                formatted.update(extra)

            loki_metadata = formatted.get('loki_metadata')
            if loki_metadata:
                if not isinstance(loki_metadata, dict):
                    loki_metadata = {}
                del formatted['loki_metadata']

        del formatted['serialized']

        if formatted['level'].startswith('ER'):
            formatted['file'] = record.get('file').name
            formatted['path'] = record.get('file').path
            formatted['line'] = record.get('line')

            self.add_exception_details(record, formatted)

        return formatted, loki_metadata


loki_handler = LokiLoggerHandler(
    url=os.environ['LOKI_URL'],
    labels={
        'application': os.environ.get('APP_NAME')
    },
    timeout=10,
    default_formatter=CustomLoguruFormatter(),
)

logger.add(
    sink=loki_handler,
    level='DEBUG' if DEBUG else 'INFO',
)

logger.error("test error message")

"""Application"""
app = Flask(__name__)

"""Metrics"""
def metrics_grouping_rule(request):
    return f'{request.method}_{request.path}'


metrics = PrometheusMetrics(app, group_by=metrics_grouping_rule)

metrics.info(
    name=os.environ.get('APP_NAME'),
    description='Flask CRUD API example',
    version=os.environ.get('APP_VERSION')
)

"""Database and data model"""
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('POSTGRES_DB_URI')
db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = 'users'

    pk = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)

    def json(self):
        return {'pk': self.pk, 'login': self.login, 'email': self.email}


with app.app_context():
    db.create_all()

"""API routes"""
RequestId(app)


def is_ready():
    try:
        db.session.execute(text('SELECT 1'))
        return True
    except OperationalError:
        return False


def get_api_logger(**kwargs):
    return logger.bind(
        ip_address=request.remote_addr,
        method=request.method,
        path=request.path,
        request_id=request.environ.get('REQUEST_ID', ''),
        **kwargs
    )


@app.route('/ready', methods=['GET'])
@metrics.do_not_track()
def ready():
    api_logger = get_api_logger()

    if is_ready():
        output = {'message': 'The service is ready'}
        status_code = 200
    else:
        output = {'message': 'The service is not ready'}
        status_code = 503

    api_logger.debug(output['message'])
    return make_response(jsonify(output), status_code)


@app.route('/health', methods=['GET'])
@metrics.do_not_track()
def health():
    api_logger = get_api_logger()

    output = {'message': 'The service is healthy'}
    status_code = 200

    api_logger.debug(output['message'])
    return make_response(jsonify(output), status_code)


@app.route('/users', methods=['GET'])
def get_users():
    api_logger = get_api_logger()

    try:
        users = User.query.all()

        data = [user.json() for user in users]
        status_code = 200

        output = {'message': 'All users being read'}
        api_logger.info(output['message'])

        return make_response(jsonify(data), status_code)
    except Exception:
        output = {'message': 'Error getting users'}
        status_code = 500

        api_logger.error(output['message'])

        return make_response(jsonify(output), status_code)


@app.route('/users', methods=['POST'])
def create_user():
    api_logger = get_api_logger()

    try:
        data = request.get_json()

        new_user = User(login=data['login'], email=data['email'])
        db.session.add(new_user)
        db.session.commit()

        db.session.flush()

        output = {'message': 'User created'}
        status_code = 201

        with api_logger.contextualize(user_id=new_user.pk):
            api_logger.info(output['message'])

        return make_response(jsonify(output), status_code)
    except Exception:
        output = {'message': 'Error creating user'}
        status_code = 500

        api_logger.error(output['message'])

        return make_response(jsonify(output), status_code)


@app.route('/users/<int:pk>', methods=['GET'])
def get_user(pk):
    api_logger = get_api_logger()

    try:
        user = User.query.filter_by(pk=pk).first()

        if user:
            data = {'user': user.json()}
            status_code = 200

            with api_logger.contextualize(user_id=pk):
                api_logger.info('User being read')

            return make_response(jsonify(data), status_code)
        else:
            output = {'message': 'User not found'}
            status_code = 404

            api_logger.warning(output['message'])

            return make_response(jsonify(output), status_code)
    except Exception:
        output = {'message': 'Error getting user'}
        status_code = 500

        api_logger.error(output['message'])

        return make_response(jsonify(output), status_code)


@app.route('/users/<int:pk>', methods=['PUT'])
def update_user(pk):
    api_logger = get_api_logger()

    try:
        user = User.query.filter_by(pk=pk).first()
        if user:
            data = request.get_json()

            user.login = data['login']
            user.email = data['email']
            db.session.commit()

            output = {'message': 'User updated'}
            status_code = 200

            with api_logger.contextualize(user_id=pk):
                api_logger.info(output['message'])

            return make_response(jsonify(data), status_code)
        else:
            output = {'message': 'User not found'}
            status_code = 404

            api_logger.warning(output['message'])

            return make_response(jsonify(output), status_code)
    except Exception:
        output = {'message': 'Error updating user'}
        status_code = 500

        logger.error(output['message'])

        return make_response(jsonify(output), status_code)


@app.route('/users/<int:pk>', methods=['DELETE'])
def delete_user(pk):
    api_logger = get_api_logger()

    try:
        user = User.query.filter_by(pk=pk).first()
        if user:
            db.session.delete(user)
            db.session.commit()

            output = {'message': 'User deleted'}
            status_code = 200

            with api_logger.contextualize(user_id=pk):
                api_logger.info(output['message'])

            return make_response(jsonify(output), status_code)
        else:
            output = {'message': 'User not found'}
            status_code = 404

            api_logger.warning(output['message'])

            return make_response(jsonify(output), status_code)
    except Exception:
        output = {'message': 'Error deleting user'}
        status_code = 500

        api_logger.error(output['message'])

        return make_response(jsonify(output), status_code)


if __name__ == '__main__':
    app.run(
        host=os.environ.get('APP_HOST'),
        port=os.environ.get('APP_PORT')
    )

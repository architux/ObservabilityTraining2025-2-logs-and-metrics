import json
import os
import sys

from flask import Flask, request, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from loguru import logger
from request_id import RequestId
from sqlalchemy.sql import text
from sqlalchemy.exc import OperationalError


def serialize(record):
    subset = {
        'timestamp': record['time'].isoformat(),
        'level': record['level'].name,
        'message': record['message'],
    }

    extra_keys = ['request_id', 'user_id']

    for extra_key in extra_keys:
        if extra_key in record['extra'].keys():
            subset[extra_key] = record['extra'][extra_key]

    return json.dumps(subset)


def patching(record):
    record['extra']['serialized'] = serialize(record)


logger.remove(0)
logger = logger.patch(patching)
logger.add(sys.stdout, format='{extra[serialized]}')


logger.debug('Happy logging with structlog!')

app = Flask(__name__)
RequestId(app)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DB_URL')
db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = 'users'

    pk = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)

    def json(self):
        return {'pk': self.pk, 'login': self.login, 'email': self.email}


def is_ready():
    try:
        db.session.execute(text('SELECT 1'))
        return True
    except OperationalError:
        return False


with app.app_context():
    db.create_all()


@app.route('/health', methods=['GET'])
def health():
    request_id = request.environ.get('REQUEST_ID', '')
    context_logger = logger.bind(request_id=request_id)

    output = {'message': 'The service is healthy'}
    status_code = 200

    context_logger.debug(output['message'])
    return make_response(jsonify(output), status_code)


@app.route('/ready', methods=['GET'])
def ready():
    request_id = request.environ.get('REQUEST_ID', '')
    context_logger = logger.bind(request_id=request_id)

    if is_ready():
        output = {'message': 'The service is ready'}
        status_code = 200
    else:
        output = {'message': 'The service is not ready'}
        status_code = 503

    context_logger.debug(output['message'])
    return make_response(jsonify(output), status_code)


@app.route('/users', methods=['GET'])
def get_users():
    request_id = request.environ.get('REQUEST_ID', '')
    context_logger = logger.bind(request_id=request_id)

    try:
        users = User.query.all()

        data = [user.json() for user in users]
        status_code = 200

        output = {'message': 'All users shown'}
        context_logger.info(output['message'])

        return make_response(jsonify(data), status_code)
    except Exception:
        output = {'message': 'Error getting users'}
        status_code = 500

        context_logger.error(output['message'])

        return make_response(jsonify(output), status_code)


@app.route('/users', methods=['POST'])
def create_user():
    request_id = request.environ.get('REQUEST_ID', '')
    context_logger = logger.bind(request_id=request_id)

    try:
        data = request.get_json()

        new_user = User(login=data['login'], email=data['email'])
        db.session.add(new_user)
        db.session.commit()

        db.session.flush()

        output = {'message': 'User created'}
        status_code = 201

        context_logger.bind(user_id=new_user.pk)
        context_logger.info(output['message'])

        return make_response(jsonify(output), status_code)
    except Exception:
        output = {'message': 'Error creating user'}
        status_code = 500

        context_logger.error(output['message'])

        return make_response(jsonify(output), status_code)


@app.route('/users/<int:pk>', methods=['GET'])
def get_user(pk):
    request_id = request.environ.get('REQUEST_ID', '')
    context_logger = logger.bind(request_id=request_id, user_id=pk)

    try:
        user = User.query.filter_by(pk=pk).first()

        if user:
            data = {'user': user.json()}
            status_code = 200

            context_logger.info('User shown')

            return make_response(jsonify(data), status_code)
        else:
            output = {'message': 'User not found'}
            status_code = 404

            context_logger.info(output['message'])

            return make_response(jsonify(output), status_code)
    except Exception:
        output = {'message': 'Error getting user'}
        status_code = 500

        context_logger.error(output['message'])

        return make_response(jsonify(output), status_code)


@app.route('/users/<int:pk>', methods=['PUT'])
def update_user(pk):
    request_id = request.environ.get('REQUEST_ID', '')
    context_logger = logger.bind(request_id=request_id, user_id=pk)

    try:
        user = User.query.filter_by(pk=pk).first()
        if user:
            data = request.get_json()

            user.login = data['login']
            user.email = data['email']
            db.session.commit()

            output = {'message': 'User updated'}
            status_code = 200

            context_logger.info(output['message'])

            return make_response(jsonify(data), status_code)
        else:
            output = {'message': 'User not found'}
            status_code = 404

            logger.info(output['message'])

            return make_response(jsonify(output), status_code)
    except Exception:
        output = {'message': 'Error updating user'}
        status_code = 500

        logger.error(output['message'])

        return make_response(jsonify(output), status_code)


@app.route('/users/<int:pk>', methods=['DELETE'])
def delete_user(pk):
    request_id = request.environ.get('REQUEST_ID', '')
    context_logger = logger.bind(request_id=request_id, user_id=pk)

    try:
        user = User.query.filter_by(pk=pk).first()
        if user:
            db.session.delete(user)
            db.session.commit()

            output = {'message': 'User deleted'}
            status_code = 200

            context_logger.info(output['message'])

            return make_response(jsonify(output), status_code)
        else:
            output = {'message': 'User not found'}
            status_code = 404

            context_logger.info(output['message'])

            return make_response(jsonify(output), status_code)
    except Exception:
        output = {'message': 'Error deleting user'}
        status_code = 500

        context_logger.error(output['message'])

        return make_response(jsonify(output), status_code)


if __name__ == '__main__':
    app.run(host=os.environ.get('APP_HOST'), port=os.environ.get('APP_PORT'))

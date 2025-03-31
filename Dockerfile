FROM python:3.12-alpine

ARG APP_PORT

ENV APP_HOST ${APP_HOST}
ENV APP_PORT ${APP_PORT}

WORKDIR /app

COPY requirements.txt ./

RUN pip install -r requirements.txt

COPY . .

EXPOSE ${APP_PORT}

CMD flask run --host=${APP_HOST} --port=${APP_PORT}

# ObservabilityTraining2025-2-logs-and-metrics

An example CRUD service backed by Flask and PostgreSQL database.

Structural logging by Loguru, logs aggregation by Loki.

Application and database metrics gathering by Prometheus, visualization by Grafana.

Should be started via Docker Compose with the `.env` file having all the necessary environmental variables, as stated in the `.env_example` file.  

## API Endpoints

### Health Check Endpoints

* GET `/health`: Liveness probe
* GET `/ready`: Readiness probe

### CRUD Endpoints

* GET `/users`: Get all users
* POST `/users`: Create a new user
```json 
{"login": "John Dow", "email": "john_dow@mail.com"}
```
* GET `/users/<user_id>`: Get a particular user by ID
* PUT `/users/<user_id>`: Update a particular user by ID
```json
{"login": "John Dow", "email": "john_dow@mail.com"}
```
* DELETE `/users/<user_id>`: Delete a particular user by ID

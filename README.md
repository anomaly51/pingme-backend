# Ping Me

A fast and reliable backend API built with FastAPI and PostgreSQL.

## Technologies
* **Language:** Python 3.12
* **Framework:** FastAPI
* **Database:** PostgreSQL & SQLAlchemy (asyncpg)
* **Package Manager:** Poetry
* **Containerization:** Docker / Docker Compose
* **Version Control:** Git (Merge Request flow)

## How To Run Locally

### 1. Clone the repository

```bash
git clone https://github.com/anomaly51/pingme-backend
cd ping-me
```

### 2. Install dependencies

Install Python dependencies using Poetry:

```bash
poetry install
```

### 3. Setup pre-commit hooks

Install pre-commit hooks for code quality:

```bash
pre-commit install
```

### 4. Setup Environment Variables

Create a .env file in the root directory to set up your database credentials. You can copy the provided example file:

```bash
cp .env.example .env
```

### 5. Run locally (without Docker)

For development, you can run the application locally:

```bash
poetry run uvicorn app.main:app --reload
```

The API will be available at http://localhost:8000.

### 6. Run with Docker Compose

Alternatively, build the images and start the containers in the background:

```bash
docker compose up --build -d
```

### 7. Check the API Documentation (Swagger)

Once the application is running, open your web browser and navigate to:

- [Swagger UI](http://localhost:8000/docs)
- [ReDoc](http://localhost:8000/redoc)

### 8. Running Tests

To run the test suite:

```bash
poetry run pytest
```

### Stopping the project

To stop and remove the containers, run:

```bash
docker compose down
```
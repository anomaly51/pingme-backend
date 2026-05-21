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
git clone https://github.com/Gamubells/pingme-backend
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

Start the isolated PostgreSQL test database:

```bash
docker compose up -d test_db
```

Run the test suite locally:

```bash
poetry run pytest
```

Or run tests inside Docker:

```bash
docker compose --profile testing run --rm test_runner
```

The local test database URL is:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://test_user:test_password@localhost:5435/test_db
```

### Stopping the project

To stop and remove the containers, run:

```bash
docker compose down
```

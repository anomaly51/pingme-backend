from fastapi import FastAPI


app = FastAPI(
    title="ping me Project API", description="FastAPI with database PostgreSQL.", version="0.1.0"
)


@app.get("/", tags=["System Checks"])
async def root():
    """
    **Check server status.**
    """
    return {"message": "Server is running!"}

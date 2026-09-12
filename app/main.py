from fastapi import FastAPI

app = FastAPI(
    title="Axiom",
    description="Autonomous market intelligence and research system",
    version="0.1.0",
)

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "axiom",
    }
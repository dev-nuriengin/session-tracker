from fastapi import FastAPI

app = FastAPI(title="Session Tracker API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"app": "session-tracker", "message": "backend is running"}

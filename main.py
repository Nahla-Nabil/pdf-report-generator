from fastapi import FastAPI

app = FastAPI(title="PDF report generator")


@app.get("/health")
def health():
    return {"status": "ok"}

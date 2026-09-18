"""Local HTTP entry point. No application data or login actions are served here."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)


@app.middleware("http")
async def redirect_to_local_https(request: Request, call_next):
    if request.method not in {"GET", "HEAD"}:
        response = JSONResponse({"detail": "Use HTTPS before submitting data."}, status_code=426)
    else:
        # Fixed origin: never trust a client-supplied Host for this redirect.
        target = "https://localhost:8443" + request.url.path
        if request.url.query:
            target += "?" + request.url.query
        response = RedirectResponse(target, status_code=307)
    response.headers["Cache-Control"] = "no-store"
    return response

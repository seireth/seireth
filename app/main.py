"""Application assembly, dispatcher lifetime, and built frontend serving."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from .api.router import router
from .worker import dispatcher


@asynccontextmanager
async def lifespan(_app: FastAPI):
    dispatcher.start()
    try:
        yield
    finally:
        dispatcher.stop()


app = FastAPI(title="Seireth", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    if not dispatcher.ready:
        raise HTTPException(503, "assessment dispatcher unavailable")
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/app/")


def serve_frontend(application: FastAPI, directory: Path):
    if (directory / "index.html").is_file():

        def require_asset(request: Request):
            path = directory / request.url.path.removeprefix("/app/")
            if path.suffix and (
                not path.resolve().is_relative_to(directory.resolve())
                or not path.is_file()
            ):
                raise HTTPException(404, "asset not found")

        frontend = APIRouter(dependencies=[Depends(require_asset)])
        frontend.frontend(
            "/app",
            directory=directory,
            fallback="index.html",
            check_dir=True,
        )
        application.include_router(frontend)
    else:

        @application.get("/app", include_in_schema=False)
        @application.get("/app/{path:path}", include_in_schema=False)
        def missing_frontend(path: str = ""):
            raise HTTPException(
                503,
                "GUI is not built. Run npm --prefix app/web ci and npm --prefix app/web run build, then restart the API.",
            )


serve_frontend(app, Path(__file__).parent / "web" / "dist")

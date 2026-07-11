from fastapi import FastAPI

from weatherflow import __version__
from weatherflow.api.schemas import HealthResponse
from weatherflow.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    app = FastAPI(title="WeatherFlow Core", version=__version__)
    app.state.settings = resolved_settings

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    return app


app = create_app()

import uvicorn

from issue_resolver.api.main import app
from issue_resolver.config import settings


def run() -> None:
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()

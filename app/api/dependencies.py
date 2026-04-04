from typing import Annotated

from fastapi import Depends, Request

from app.store.job_store import InMemoryJobStore


def get_job_store(request: Request) -> InMemoryJobStore:
    """Retrieve the shared job store from the app state."""
    return request.app.state.job_store


def get_agent(request: Request):
    """Retrieve the shared agent instance from the app state."""
    return request.app.state.agent


JobStoreDep = Annotated[InMemoryJobStore, Depends(get_job_store)]
AgentDep = Annotated[object, Depends(get_agent)]

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.db.seekdb import SeekDB
from app.services.assistant import Assistant
from app.services.embeddings import EmbeddingService
from app.services.powercontext import PowerContextClient


def get_request_db(request: Request) -> SeekDB:
    return request.app.state.db


def get_request_pc(request: Request) -> PowerContextClient:
    return request.app.state.pc


def get_request_embeddings(request: Request) -> EmbeddingService:
    return request.app.state.embeddings


def get_request_assistant(request: Request) -> Assistant:
    return request.app.state.assistant


DbDep = Annotated[SeekDB, Depends(get_request_db)]
PcDep = Annotated[PowerContextClient, Depends(get_request_pc)]
EmbeddingsDep = Annotated[EmbeddingService, Depends(get_request_embeddings)]
AssistantDep = Annotated[Assistant, Depends(get_request_assistant)]

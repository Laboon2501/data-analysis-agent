FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY datasource ./datasource
COPY demo ./demo
COPY evals ./evals
COPY graphs ./graphs
COPY guards ./guards
COPY llm ./llm
COPY mcp ./mcp
COPY nodes ./nodes
COPY persistence ./persistence
COPY prompts ./prompts
COPY schemas ./schemas
COPY scripts ./scripts
COPY tools ./tools

RUN python -m pip install --upgrade pip \
    && python -m pip install -e .

EXPOSE 8000

CMD ["python", "scripts/run_api.py", "--host", "0.0.0.0", "--port", "8000"]

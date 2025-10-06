FROM python:3.12-slim AS build

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /src

# Copy dependency files and README (required by pyproject.toml)
COPY pyproject.toml uv.lock README.md ./

# Copy source code (required for building the package)
COPY src ./src

# Install dependencies
RUN uv sync --frozen --no-dev

# Build wheel
RUN uv build --wheel

FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy built wheel
COPY --from=build /src/dist/*.whl /tmp/

# Install the package
RUN uv pip install --system /tmp/*.whl && rm /tmp/*.whl

ENTRYPOINT ["unhook-tanha"]

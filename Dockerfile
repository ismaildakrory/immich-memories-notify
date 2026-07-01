ARG COPY_SOURCE=false

FROM python:3.11-alpine AS base

# Install dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Create app directory
WORKDIR /app
RUN mkdir -p /app/state

# Stage: local development (source files mounted as volume)
FROM base AS copy-false

# Stage: production build (source files baked in)
FROM base AS copy-true
COPY VERSION /app/VERSION
COPY notify/ /app/notify/
COPY custom_templates/ /app/custom_templates/
COPY config.yaml /app/config.yaml

# Final stage
FROM copy-${COPY_SOURCE} AS final

ENTRYPOINT ["python", "-m", "notify"]
CMD []

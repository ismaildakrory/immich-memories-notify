# Immich Memories Notify
# Lightweight Python container for sending memory notifications

FROM python:3.11-alpine

# Install dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Create app directory
WORKDIR /app

# Source files are mounted as volume (not copied)
# This allows easy editing without rebuilding

# Use entrypoint so arguments work properly
ENTRYPOINT ["python", "-m", "notify"]
CMD []

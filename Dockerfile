# Immich Memories Notify
# Lightweight Python container for sending memory notifications

FROM python:3.11-alpine

# Install dependencies
RUN pip install --no-cache-dir requests pyyaml

# Create app directory
WORKDIR /app

# Source files are mounted as volume (not copied)
# This allows easy editing without rebuilding

# Use entrypoint so arguments work properly
ENTRYPOINT ["python", "notify.py"]
CMD []

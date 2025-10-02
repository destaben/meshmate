# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY main.py .
COPY schedule_manager.py .
COPY handlers/ handlers/

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash meshmate

# Create data directory for schedules persistence
RUN mkdir -p /app/data && chown meshmate:meshmate /app/data

# Switch to non-root user
USER meshmate

# Set the entrypoint to run the script
ENTRYPOINT ["python", "main.py"]
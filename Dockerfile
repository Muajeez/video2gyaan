# Use the official Python lightweight image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy the requirements file first to leverage Docker cache
COPY backend/requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project (backend and frontend folders)
COPY . .

# Expose the port Cloud Run uses
EXPOSE 8080

# Command to run the application using Uvicorn
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

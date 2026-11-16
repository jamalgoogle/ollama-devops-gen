# Small official Python image
FROM python:3.12-slim
# All files will live in /app
WORKDIR /app
# Copy requirements first: Docker can cache this layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copy the source code
COPY app.py .
# Do NOT run as root: create a normal user
RUN useradd --uid 10001 --no-create-home appuser
USER 10001
# The app listens on port 8080
EXPOSE 8080
# gunicorn = a real production web server
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "app:app"]

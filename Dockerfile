FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY . .
ENV PYTHONPATH="${PYTHONPATH}:/app"
CMD ["python", "-m", "app.main"]  # <-- Sửa thành dạng module
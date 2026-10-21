FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY client.py scid.py server.py main.py ./
ENV PORT=80
ENV PYTHONUNBUFFERED=1
EXPOSE 80
CMD ["python", "main.py"]

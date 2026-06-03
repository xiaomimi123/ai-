FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# pip 源可通过 build-arg 切换（中国大陆服务器建议传
#   --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
# 默认 pypi.org）
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

# 系统依赖（PyMuPDF/psycopg2 等）
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

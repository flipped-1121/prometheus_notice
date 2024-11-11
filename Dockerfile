FROM python:alpine

COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir

CMD ["python", "main.py"]
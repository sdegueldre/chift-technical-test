FROM python:3.12
WORKDIR /home/chift_technical_test
COPY requirements.txt requirements.txt
COPY app app
RUN pip3 install -r requirements.txt
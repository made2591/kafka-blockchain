FROM python:3

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG port
ENV port ${port}
ARG partition
ENV partition ${partition}
ARG name
ENV name ${name}

CMD python ./kafka_blockchain.py ${port} ${partition} ${name}

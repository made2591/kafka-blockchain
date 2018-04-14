FROM python:3

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG port
ARG partition
ARG name

CMD [ "python", "./kafka_blockchain.py", $port, $partition, $name]

FROM python:3

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG partition
ARG mode
ARG name

CMD [ "python", "./kafka_blockchain.py", $partition, $mode, $name]
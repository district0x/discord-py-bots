FROM python:3.11.3

WORKDIR /usr/src/app
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . . 

CMD [ "python3", "ethlanceGPT/ethlanceGPT.py" ]

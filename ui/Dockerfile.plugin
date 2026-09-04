FROM registry.access.redhat.com/ubi9/python-311:latest
USER root
WORKDIR /opt/app-root/src
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER 1001
EXPOSE 8443
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8443 --ssl-certfile /var/serving-cert/tls.crt --ssl-keyfile /var/serving-cert/tls.key"]

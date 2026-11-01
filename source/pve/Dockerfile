FROM debian:13-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f
RUN apt-get update && apt-get install -y --no-install-recommends python3 xorriso openssh-client wimtools ca-certificates && apt-get clean
WORKDIR /app
COPY . /app
ENTRYPOINT ["python3", "/app/opendeploy.py"]

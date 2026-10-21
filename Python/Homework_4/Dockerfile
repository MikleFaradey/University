FROM python@sha256:5d9e6adc9abd558bc0ce05f9ab16cef71328916fc9728f6b81e337af86a737e2
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BANK_HOST=0.0.0.0 BANK_DB=/app/data/bank.sqlite3
WORKDIR /app
RUN groupadd --gid 10001 bank && useradd --uid 10001 --gid bank --no-create-home bank \
    && mkdir /app/data && chown bank:bank /app/data
COPY --chown=bank:bank main.py /app/main.py
USER 10001:10001
EXPOSE 9999
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import socket; s=socket.create_connection(('127.0.0.1',9999),2); s.close()"]
CMD ["python", "main.py"]

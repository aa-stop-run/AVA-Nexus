FROM alpine:3.20 AS tailwind-builder
RUN apk add --no-cache curl libstdc++
RUN curl -fsSLo /usr/local/bin/tailwindcss \
    https://github.com/tailwindlabs/tailwindcss/releases/download/v4.1.18/tailwindcss-linux-x64-musl \
    && chmod +x /usr/local/bin/tailwindcss
WORKDIR /build
COPY src/ava/static/input.css src/ava/static/input.css
COPY src/ava/templates src/ava/templates
RUN tailwindcss -i src/ava/static/input.css -o src/ava/static/app.css --minify

FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install --no-cache-dir .

COPY --from=tailwind-builder /build/src/ava/static/app.css src/ava/static/app.css

EXPOSE 8000

# main.py monta "/static" a partir do caminho relativo "src/ava/static" -- por isso o
# processo tem de arrancar com /app como diretório de trabalho (WORKDIR acima), não do
# diretório do pacote instalado.
CMD ["uvicorn", "ava.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM alpine:3.20 AS tailwind-builder
RUN apk add --no-cache curl libstdc++
RUN curl -fsSLo /usr/local/bin/tailwindcss \
    https://github.com/tailwindlabs/tailwindcss/releases/download/v4.1.18/tailwindcss-linux-x64-musl \
    && chmod +x /usr/local/bin/tailwindcss
WORKDIR /build
COPY src/casa/static/input.css src/casa/static/input.css
COPY src/casa/templates src/casa/templates
RUN tailwindcss -i src/casa/static/input.css -o src/casa/static/app.css --minify

FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY --from=tailwind-builder /build/src/casa/static/app.css src/casa/static/app.css

EXPOSE 8000

CMD ["uvicorn", "casa.main:app", "--host", "0.0.0.0", "--port", "8000"]

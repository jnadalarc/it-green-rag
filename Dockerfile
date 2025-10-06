# Stage 1: Builder - Instal·la les dependències
FROM python:3.11-slim as builder

WORKDIR /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix="/install" -r requirements.txt

# Stage 2: Final - Crea la imatge final amb el codi i les dependències
FROM python:3.11-slim

WORKDIR /app

# Copia les dependències instal·lades des del builder
COPY --from=builder /install /usr/local

# AQUESTA ÚNICA LÍNIA COPIA TOT EL NECESSARI (`main.py`, `static` i `templates`)
COPY ./app /app

# L'aplicació escriu a la base de dades i puja fitxers
RUN mkdir /data

# Exposa el port on correrà l'aplicació
EXPOSE 8000

# Comanda per executar l'aplicació amb uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
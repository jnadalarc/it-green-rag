# README: passos operatius
# 1) Copia un model GGUF a /srv/llm-models (ex.: mistral-7b-instruct.Q4_K_M.gguf).
# 2) Crea carpetes /srv/llm-data/docs i /srv/llm-data/rag al node.
# 3) Configura DNS local o /etc/hosts: llm.local -> IP del Ingress Traefik de k3s.
# 4) Fes push a main. El runner self-hosted construirà i pujarà la imatge al vostre registry i farà el deploy.
# 5) Obre http://llm.local i prova.
# 6) RAG: puja .txt/.md/.log. Per PDFs, extrau text prèviament o afegeix un pas ETL.
# --- Variables ---
# Canvia aquests valors segons el teu projecte i registry
APP_NAME := mcp-rag-rapid
REGISTRY_URL ?= registry.wattega.com # El teu registry privat
TAG ?= latest
IMAGE_NAME := $(REGISTRY_URL)/$(APP_NAME):$(TAG)

# --- Comandes ---

# Construeix la imatge de Docker
build:
	@echo "Building Docker image: $(IMAGE_NAME)"
	@docker build -t $(IMAGE_NAME) .

# Puja la imatge de Docker al registry
push: build
	@echo "Pushing Docker image: $(IMAGE_NAME)"
	@docker push $(IMAGE_NAME)

# Desplega l'aplicació a Kubernetes
# Substitueix les variables als templates i aplica els manifestos
deploy:
	@echo "Deploying to Kubernetes"
	@sed -e "s|\$${APP_NAME}|$(APP_NAME)|g" \
		-e "s|\$${APP_PORT}|8000|g" \
		-e "s|\$${IMAGE}|$(IMAGE_NAME)|g" \
		k3s/app-pvc.yaml.template > k3s/app-pvc.yaml
	@sed -e "s|\$${APP_NAME}|$(APP_NAME)|g" \
		-e "s|\$${APP_PORT}|8000|g" \
		-e "s|\$${IMAGE}|$(IMAGE_NAME)|g" \
		k3s/app-deployment.yaml.template > k3s/app-deployment.yaml
	@sed -e "s|\$${APP_NAME}|$(APP_NAME)|g" \
		-e "s|\$${APP_PORT}|8000|g" \
		k3s/app-service.yaml.template > k3s/app-service.yaml
	@sed -e "s|\$${APP_NAME}|$(APP_NAME)|g" \
		-e "s|\$${APP_PORT}|8000|g" \
		k3s/app-ingress.yaml.template > k3s/app-ingress.yaml
	
	@kubectl apply -f k3s/app-pvc.yaml
	@kubectl apply -f k3s/app-deployment.yaml
	@kubectl apply -f k3s/app-service.yaml
	@kubectl apply -f k3s/app-ingress.yaml

.PHONY: build push deploy
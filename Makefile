# --- Variables ---
APP_NAME := mcp-chainlit-rag
REGISTRY_URL ?= registry.teva-empresa.com
TAG ?= latest

IMAGE_NAME := $(REGISTRY_URL)/$(APP_NAME):$(TAG)

# --- Comandes ---
# ... (la resta de comandes 'build', 'push', 'deploy' es queden igual)
# ... [Contingut del Makefile anterior]
build:
	@echo "Building Docker image: $(IMAGE_NAME)"
	@docker build -t $(IMAGE_NAME) .
	@docker build --no-cache -t $(IMAGE_NAME) .
push: build
	@echo "Pushing Docker image: $(IMAGE_NAME)"
	@docker push $(IMAGE_NAME)

deploy:
	@echo "Deploying to Kubernetes"
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
	
	@kubectl apply -f k3s/app-deployment.yaml
	@kubectl apply -f k3s/app-service.yaml
	@kubectl apply -f k3s/app-ingress.yaml

.PHONY: build push deploy
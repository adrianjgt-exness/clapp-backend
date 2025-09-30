.PHONY: lint test run format

# Run linting using ruff
lint:
	@echo "Running lints"
	ruff . --output-format=full

# Run tests using pytest
test:
	@echo "Running tests"
	pytest -v tests/

# Start FastAPI app locally
run:
	@echo "Starting FastAPI app on http://localhost:8000"
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Format code using ruff
format:
	@echo "Auto-formatting code"
	ruff format .

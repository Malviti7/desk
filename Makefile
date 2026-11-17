.PHONY: install web demo serve mcp test

install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[coinbase,dev]"
	cd web && npm install && npm run build

web:
	cd web && npm run build

demo:
	desk serve --demo

serve:
	desk serve

mcp:
	desk mcp

test:
	pytest -q

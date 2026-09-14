.PHONY: install setup test lint format clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff
DATA_DIR := mcp-server/profile_store/data

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt
	$(MAKE) setup

# Bootstrap the git-ignored, personal data files from their tracked
# examples, but never overwrite real data that's already there.
setup:
	@if [ ! -f $(DATA_DIR)/experience_profile.json ]; then \
		cp $(DATA_DIR)/experience_profile.example.json $(DATA_DIR)/experience_profile.json; \
		echo "Created $(DATA_DIR)/experience_profile.json from the placeholder example — replace it with your real experience before using this for real proposals."; \
	fi
	@if [ ! -f $(DATA_DIR)/proposal_log.json ]; then \
		cp $(DATA_DIR)/proposal_log.json.example $(DATA_DIR)/proposal_log.json; \
		echo "Created empty $(DATA_DIR)/proposal_log.json."; \
	fi

test: setup
	$(PYTHON) -m pytest -v

lint:
	$(RUFF) check .
	$(RUFF) format --check .

format:
	$(RUFF) format .

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache mcp-server/profile_store/__pycache__ tests/__pycache__

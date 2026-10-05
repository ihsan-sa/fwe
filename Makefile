# make check runs the whole test suite, the gate a change must pass (fwe has no CI).
# It uses .venv when there is one (make venv), else python3 with pytest installed.
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: check venv

check:
	$(PY) -m pytest -q tests

venv:
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt

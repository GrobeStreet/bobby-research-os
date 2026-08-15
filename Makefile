SHELL := /bin/bash

.PHONY: reproduce test

reproduce:
	./reproduce.sh

test:
	pytest -q

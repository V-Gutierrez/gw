.PHONY: build publish clean

build:
	python3 -m build

publish: build
	python3 -m twine upload dist/*

publish-test: build
	python3 -m twine upload --repository testpypi dist/*

clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info

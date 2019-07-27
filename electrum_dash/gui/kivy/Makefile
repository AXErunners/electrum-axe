PYTHON = python3

# needs kivy installed or in PYTHONPATH

.PHONY: theming prepare prepare-testnet apk apk-testnet release release-testnet clean

theming:
	$(PYTHON) -m kivy.atlas theming/light 1024 theming/light/*.png
prepare:
	# running pre build setup
	@cp tools/buildozer.spec ../../../buildozer.spec
	# copy electrum-dash to main.py
	@cp ../../../electrum-dash ../../../main.py
prepare-testnet:
	@-cd ../../..; sed -r "s:^(title =.*):\1 Testnet:" -i buildozer.spec
	@-cd ../../..; sed -r "s:^(package.nam.*):\1_Testnet:" -i buildozer.spec
	@-cd ../../..; sed -r "s:^(presp.*).png:\1_testnet.png:" -i buildozer.spec
	@-cd ../../..; sed -r "s:^(icon.*).png:\1-testnet.png:" -i buildozer.spec
apk:
	@make prepare
	@-cd ../../..; buildozer android debug
	@make clean
apk-testnet:
	@make prepare
	@make prepare-testnet
	@-cd ../../..; buildozer android debug
	@make clean
release:
	@make prepare
	@-cd ../../..; buildozer android release
	@make clean
release-testnet:
	@make prepare
	@make prepare-testnet
	@-cd ../../..; buildozer android release
	@make clean
clean:
	# Cleaning up
	# rename main.py to electrum-dash
	@-rm ../../../main.py
	# remove buildozer.spec
	@-rm ../../../buildozer.spec

include Makefile.variable

all:
	cd utils && $(MAKE)
	cd algorithms && $(MAKE)

clean:
	cd utils && $(MAKE) clean
	cd algorithms && $(MAKE) clean

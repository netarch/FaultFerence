include ../Makefile.variable

LIBDIR = -L../sparsehash/libs
INCLUDE = -I../sparsehash/include
ROOTDIR = $(shell pwd)

OBJS = flow.o logdata.o utils.o

all: libflock.a

libflock.a: $(OBJS)
	ar cr libflock.a $(OBJS)

flow.o: flow.cpp utils.cpp flow.h defs.h utils.h
	$(CC) $(INCLUDE) $(CFLAGS) -c flow.cpp

utils.o: utils.cpp utils.h flow.h defs.h
	$(CC) $(INCLUDE) $(CFLAGS) -c utils.cpp

logdata.o: logdata.cpp utils.cpp logdata.h utils.h flow.h defs.h
	$(CC) $(INCLUDE) $(CFLAGS) -c logdata.cpp

clean:
	rm -f *.o libflock.a

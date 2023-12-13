include ../Makefile.variable

ROOTDIR=$(shell pwd)/..
VPATH = ${ROOTDIR}/algorithms ${ROOTDIR}/utils
LIBDIR = -L../sparsehash/libs -L../utils/ -L../algorithms/
INCLUDE = -I../sparsehash/include -I../utils/ -I../algorithms/
LIBS = -lflock -lflockalg

ESTIMATOR_MAINS = black_hole_estimator_agg

OBJS = black_hole_utils.o

all: $(ESTIMATOR_MAINS)

$(ESTIMATOR_MAINS): %: %.cpp $(OBJS)
	$(CC) $(INCLUDE) $(CFLAGS) ${OBJS} -o $@ $< ${LIBDIR} ${LIBS}

black_hole_utils.o: black_hole_utils.cpp black_hole_utils.h flow.h defs.h utils.h utils.cpp
	$(CC) $(INCLUDE) $(CFLAGS) -c black_hole_utils.cpp

clean:	
	rm -f *.o $(ESTIMATOR_MAINS)

include ../Makefile.variable

ROOTDIR=$(shell pwd)/..
VPATH = ${ROOTDIR}/algorithms ${ROOTDIR}/utils
LIBDIR = -L../sparsehash/libs -L../utils/ -L../algorithms/
INCLUDE = -I../sparsehash/include -I../utils/ -I../algorithms/
LIBS = -lflock -lflockalg

ESTIMATOR_MAINS = estimator_agg

OBJS = faultference_utils.o

all: $(ESTIMATOR_MAINS)

$(ESTIMATOR_MAINS): %: %.cpp $(OBJS)
	$(CC) $(INCLUDE) $(CFLAGS) ${OBJS} -o $@ $< ${LIBDIR} ${LIBS}

faultference_utils.o: faultference_utils.cpp faultference_utils.h flow.h defs.h utils.h utils.cpp
	$(CC) $(INCLUDE) $(CFLAGS) -c faultference_utils.cpp

clean:	
	rm -f *.o $(ESTIMATOR_MAINS)

include ../Makefile.variable

ROOTDIR=$(shell pwd)/..
VPATH = ${ROOTDIR}/algorithms ${ROOTDIR}/utils
LIBDIR = -L../sparsehash/libs -L../utils/ -L../algorithms/
INCLUDE = -I../sparsehash/include -I../utils/ -I../algorithms/
LIBS = -lflock -lflockalg

ESTIMATOR_MAINS = estimator_agg

OBJS = microchange.o faultference_utils.o 

all: $(ESTIMATOR_MAINS) flock_calibrate

$(ESTIMATOR_MAINS): %: %.cpp $(OBJS)
	$(CC) $(INCLUDE) $(CFLAGS) ${OBJS} -o $@ $< ${LIBDIR} ${LIBS}

flock_calibrate: %: %.cpp $(OBJS) common_testing_system.o
	$(CC) $(INCLUDE) $(CFLAGS) ${OBJS} common_testing_system.o -o $@ $< ${LIBDIR} ${LIBS}

microchange.o: microchange.h flow.h defs.h utils.h utils.cpp
	$(CC) $(INCLUDE) $(CFLAGS) -c microchange.cpp

faultference_utils.o: microchange.h faultference_utils.cpp faultference_utils.h flow.h defs.h utils.h utils.cpp
	$(CC) $(INCLUDE) $(CFLAGS) -c faultference_utils.cpp

common_testing_system.o: common_testing_system.cpp common_testing_system.h utils.o flow.o logdata.o
	$(CC) $(INCLUDE) $(CFLAGS) -c common_testing_system.cpp 

clean:	
	rm -f *.o $(ESTIMATOR_MAINS) flock_calibrate

include ../Makefile.variable

ROOTDIR=${shell pwd}/..
VPATH=${ROOTDIR}/utils
LIBDIR = -L../sparsehash/libs -L../utils/
INCLUDE = -I../sparsehash/include -I../utils/

ESTIMATOR_OBJS = bayesian_net.o bayesian_net_continuous.o doubleO7.o score.o net_bouncer.o bayesian_net_sherlock.o

all: libflockalg.a

libflockalg.a: $(ESTIMATOR_OBJS)
	ar cr libflockalg.a $(ESTIMATOR_OBJS)


$(ESTIMATOR_OBJS): %.o: %.cpp %.h estimator.h flow.h utils.h logdata.h defs.h utils.h utils.cpp
	$(CC) $(INCLUDE) $(CFLAGS) -c $< $(LIBDIR) -o $@ 

clean:	
	rm -f *.o libflockalg.a

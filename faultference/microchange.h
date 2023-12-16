#ifndef __MICROCHANGE__
#define __MICROCHANGE__

#include "defs.h"
#include <iostream>
#include <list>
#include <unordered_map>
#include <vector>
#include <set>
using namespace std;

enum MicroChangeType { REMOVE_LINK, ACTIVE_PROBE };

class MicroChange {
  public:
    int cost = 1;
    MicroChangeType mc_type;

    MicroChange();
    virtual ostream& Print(ostream &os) { assert (false); };
};

class RemoveLinkMc : public MicroChange {
    Link remove_link;

  public:
    RemoveLinkMc(Link _remove_link);
    ostream &Print(ostream &os) {
        os << "[MicroChange type " << "REMOVE_LINK ";
        os << remove_link;
        os << "]";
        return os;
    }
};

class ActiveProbeMc : public MicroChange {
    int src, dst, nprobes;

  public:
    ActiveProbeMc(int _src, int _dst, int _nprobes);
    ostream& Print(ostream &os) {
        os << "[MicroChange type " << "ACTIVE_PROBE ";
        os << src << " " << dst << " " << nprobes;
        os << "]";
        return os;
    }
};

inline ostream& operator<<(ostream &os, MicroChange* mc) {
    return mc->Print(os);
}

#endif

#ifndef __MICROCHANGE__
#define __MICROCHANGE__

#include "defs.h"
#include <iostream>
#include <list>
#include <set>
#include <unordered_map>
#include <vector>
using namespace std;

enum MicroChangeType { REMOVE_LINK, ACTIVE_PROBE };

class MicroChange {
  public:
    int cost = 1;
    int time_to_diagnose = 1;
    MicroChangeType mc_type;

    MicroChange();
    virtual ostream &Print(ostream &os) { assert(false); };
};

class RemoveLinkMc : public MicroChange {
    Link remove_link;

  public:
    int cost = 10;
    int time_to_diagnose = 10;
    RemoveLinkMc(Link _remove_link);
    ostream &Print(ostream &os) {
        os << "[MicroChange type "
           << "REMOVE_LINK ";
        os << remove_link;
        os << "]";
        return os;
    }
};

class ReplaceLinkMc : public MicroChange {
    Link replace_link;

    public:
      int cost = 100;
      int time_to_diagnose = 10;

      ReplaceLinkMc(Link _replace_link);
      ostream &Print(ostream &os) {
          os << "[MicroChange type "
            << "REPLACE_LINK ";
          os << replace_link;
          os << "]";
          return os;
      } 
};


class ActiveProbeMc : public MicroChange {
    int src, dst, srcport, dstport, nprobes;
    // active probes can optionally be sent with a different src, dst in the
    // 5-tuple header than the actual src from where they are sent, or from the
    // actual dst where they are intercepted
    int header_src, header_dst;

  public:
    int cost = 100;
    int time_to_diagnose = 1;
    ActiveProbeMc(int _src, int _dst, int _srcport, int _dstport, int _nprobes,
                  int _header_src, int _header_dst);
    ostream &Print(ostream &os) {
        os << "[MicroChange type "
           << "ACTIVE_PROBE ";
        os << src << " " << dst << " ";
        os << srcport << " " << dstport << " ";
        os << nprobes << " " << header_src << " " << header_dst;
        os << "]";
        return os;
    }
};

inline ostream &operator<<(ostream &os, MicroChange &mc) {
    return mc.Print(os);
}

#endif

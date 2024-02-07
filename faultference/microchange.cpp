#include "microchange.h"
#include "defs.h"
#include <iostream>
#include <list>
#include <set>
#include <unordered_map>
#include <vector>

using namespace std;

MicroChange::MicroChange() {}

RemoveLinkMc::RemoveLinkMc(Link _remove_link) : remove_link(_remove_link) {
    mc_type = REMOVE_LINK;
}

ActiveProbeMc::ActiveProbeMc(int _src, int _dst, int _srcport, int _dstport,
                             int _nprobes, int _header_src, int _header_dst)
    : src(_src), dst(_dst), srcport(_srcport), dstport(_dstport),
      nprobes(_nprobes), header_src(_header_src), header_dst(_header_dst) {
    mc_type = ACTIVE_PROBE;
}

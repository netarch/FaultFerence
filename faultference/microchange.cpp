#include "defs.h"
#include <iostream>
#include <list>
#include <unordered_map>
#include <vector>
#include <set>
#include "microchange.h"

using namespace std;

MicroChange::MicroChange() {}

RemoveLinkMc::RemoveLinkMc(Link _remove_link): remove_link(_remove_link) {
    mc_type = REMOVE_LINK; 
}

ActiveProbeMc::ActiveProbeMc(int _src, int _dst, int _nprobes)
    : src(_src), dst(_dst), nprobes(_nprobes) {
    mc_type = ACTIVE_PROBE;
}

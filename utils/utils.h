#ifndef __FAULT_LOCALIZE_UTILS__
#define __FAULT_LOCALIZE_UTILS__

#include "flow.h"
#include <map>
#include <mutex>
#include <set>
#include <shared_mutex>
#include <unordered_map>
#include <utility>
//#include <charconv>
#include <algorithm>
#include <sparsehash/dense_hash_map>
#include <string>
using google::dense_hash_map;
using namespace std;

inline constexpr bool PARALLEL_IO = false;
const bool CONSIDER_REVERSE_PATH = false;

extern bool ACTIVE_PROBES_PATH_KNOWN;
extern bool PATH_KNOWN;
extern bool VERBOSE;
extern bool CONSIDER_DEVICE_LINK;
extern bool TRACEROUTE_BAD_FLOWS;
enum InputFlowType {
    ACTIVE_FLOWS,
    ALL_FLOWS,
    PROBLEMATIC_FLOWS,
    APPLICATION_FLOWS
};
extern InputFlowType INPUT_FLOW_TYPE;

const bool MACL_UNION_HYPOTHESES = true;
const int NUM_HYPOTHESIS_FOR_UNION = 5;
extern bool MISCONFIGURED_ACL;

// All trace files have hosts numbered as host + OFFSET_HOST
const int OFFSET_HOST = 10000;

struct MemoizedPaths {
    vector<Path *> paths;
    shared_mutex lock;
    MemoizedPaths() {}
    MemoizedPaths(MemoizedPaths &mpaths) { paths = mpaths.paths; }
    // Doesn't check for duplicates
    void AddPath(vector<int> &vi_path) {
        if constexpr (PARALLEL_IO)
            lock.lock();
        paths.push_back(new Path(vi_path));
        if constexpr (PARALLEL_IO)
            lock.unlock();
    }
    void AddPath(Path *path) {
        if constexpr (PARALLEL_IO)
            lock.lock();
        assert (path->size() >= 0);
        paths.push_back(path);
        if constexpr (PARALLEL_IO)
            lock.unlock();
    }
    Path *GetPath(vector<int> &vi_path) {
        if constexpr (PARALLEL_IO)
            lock.lock();
        Path *ret = NULL;
        for (Path *path : paths) {
            if (*path == vi_path) {
                ret = path;
                break;
            }
        }
        if (ret == NULL) {
            ret = new Path(vi_path);
            paths.push_back(ret);
            cout << "Path not found " << vi_path << endl;
            assert(vi_path.size() == 0 and ret->size()==0);
        }
        if constexpr (PARALLEL_IO)
            lock.unlock();
        return ret;
    }
    void GetAllPaths(vector<Path *> **result) { *result = &paths; }
};

struct FlowLines {
    char *fid_c, *fpt_c, *fprt_c;
    vector<char *> ss_c;
    FlowLines() : fid_c(NULL), fpt_c(NULL), fprt_c(NULL) {}
    void FreeMemory() {
        if (fid_c != NULL)
            delete fid_c;
        if (fpt_c != NULL)
            delete fpt_c;
        if (fprt_c != NULL)
            delete fprt_c;
        for (char *c : ss_c)
            delete c;
    }
};
class LogData;

void GetAllPairShortestPaths(vector<int> &nodes, unordered_set<Link> &links,
                             LogData *result);
void GetLinkMappings(string topology_file, LogData *result,
                     bool compute_paths = false);
void GetDataFromLogFile(string trace_file, LogData *result);
void GetCompletePaths(Flow *flow, FlowLines &flow_lines, LogData *data,
                      vector<int> &temp_path, vector<int> &path_nodes,
                      vector<int> &reverse_path_nodes, int srcrack,
                      int destrack);
void ReadPath(char *path_c, vector<int> &path_nodes, vector<int> &temp_path,
              LogData *result);
void ProcessFlowPathLines(vector<char *> &lines,
                          vector<array<int, 10>> &path_nodes_list,
                          int nopenmp_threads);
void ProcessFlowLines(vector<FlowLines> &all_flow_lines, LogData *result,
                      int nopenmp_threads);
void GetDataFromLogFileParallel(string trace_file, string topology_file,
                                LogData *result, int nopenmp_threads);
void GetDataFromLogFileDistributed(string dirname, int nchunks, LogData *result,
                                   int nopenmp_threads);

inline bool HypothesisIntersectsPath(Hypothesis *hypothesis, Path *path) {
    bool link_in_path = false;
    for (int link_id : *path) {
        link_in_path = (link_in_path or (hypothesis->count(link_id) > 0));
    }
    return link_in_path;
}

inline int NumIntersectionsHypothesisPath(Hypothesis *hypothesis, Path *path) {
    int links_in_path = 0;
    for (int link_id : *path) {
        links_in_path += (hypothesis->count(link_id) > 0);
    }
    return links_in_path;
}

inline int GetTokenLength(char *str) {
    int ind = 0;
    while (str[ind] == ' ')
        ind++; // Trim initial whitespace
    while (str[ind] != '\0' and str[ind] != ' ' and str[ind] != '\n')
        ind++;
    return ind;
}

inline pair<char *, bool> to_int(char *s, int length, int &result) {
    // cout << "converting " << string(s, length) << " ";
    char *end = s + length;
    if (s == NULL || length == 0)
        return pair<char *, bool>(s, false);
    while (*s == ' ')
        ++s;
    bool negate = (s[0] == '-');
    if (*s == '+' || *s == '-')
        ++s;
    if (s == end)
        return pair<char *, bool>(s, false);

    result = 0;
    while (s != end) {
        if (*s >= '0' && *s <= '9') {
            result = result * 10 + (*s - '0');
        } else
            return pair<char *, bool>(s, false);
        ++s;
    }
    if (negate)
        result = -result;
    // cout << result << endl;
    return pair<char *, bool>(s, true);
}

inline bool GetFirstInt(char *&str, int &result) {
    while (*str == ' ')
        str++; // Trim initial whitespace
    int token_length = GetTokenLength(str);
    // auto [p, ec] = from_chars(str, str + token_length, result);
    auto [p, success] = to_int(str, token_length, result);
    // cout << "GetFirstInt " << string(str, token_length) << " : " << result <<
    // " : " << success << endl;
    str = const_cast<char *>(p);
    return success;
    // return (ec == errc());
}
/*
inline bool GetFirstInt(char* &str, int &result){
    //cout << "str " << str;
    while(*str==' ' or *str=='\n') str++; //Trim initial whitespace
    result = 0;
    while(*str>='0' and *str<='9') result = result * 10 + (*(str++) - '0');
    //cout << " result " << result << endl;;
    return (*str!='\0');
}
*/

inline bool GetFirstDouble(char *&str, double &result) {
    int token_length = GetTokenLength(str);
    char c = str[token_length];
    str[token_length] = '\0'; // temporary sentinel value
    bool all_white_space =
        all_of(str, str + token_length, [](char c) { return isspace(c); });
    // auto [p, ec] = from_chars(str, str + token_length, result);
    // str = p;
    if (!all_white_space)
        result = atof(str);
    // cout << str << " : " << result <<endl;
    str[token_length] = c;
    str += token_length;
    return !all_white_space;
}

inline bool GetString(char *&str, string &result) {
    int ind = 0;
    result.clear();
    while (*str != ' ')
        result.push_back(*(str++)); // Trim initial whitespace
    int token_length = GetTokenLength(str);
    result.clear();
    result.insert(0, str, token_length);
    str = str + token_length;
    return true;
}

inline bool GetString(char *&str, char *result) {
    // cout << "GS " << str << " : " << result << " ---> " << endl;
    while (*str != ' ' and *str != '\0' and *str != '\n')
        *(result++) = (*(str++));
    *result = '\0';
    return true;
}

inline bool StringStartsWith(const string &a, const string &b) {
    return (b.length() <= a.length() && equal(b.begin(), b.end(), a.begin()));
}

Hypothesis UnidirectionalHypothesis(Hypothesis &h, LogData *data);
PDD GetPrecisionRecallUnidirectional(Hypothesis &failed_links,
                                     Hypothesis &predicted_hypothesis,
                                     LogData *data);
PDD GetPrecisionRecall(Hypothesis &failed_links,
                       Hypothesis &predicted_hypothesis, LogData *data);

#endif

#ifndef __FAULT_LOCALIZE_DEFS__
#define __FAULT_LOCALIZE_DEFS__

#include <atomic>
#include <chrono>
#include <set>
#include <sparsehash/dense_hash_map>
#include <unordered_set>
#include <iostream>
#include <vector>
#include <iostream>
using google::dense_hash_map;

using namespace std;

//#define MAX_PATH_LENGTH 10
#define MAX_PATH_LENGTH 100 // for irregular
//#define MAX_PATH_LENGTH 5 //+1 for device level localization

// An optimized class for small vectors
//  - can accomodate a small number of elements
//  - used for storing paths in a vector type data structure
template <typename T> struct SmallVector {
    T arr[MAX_PATH_LENGTH];
    char arr_size, ind;
    SmallVector(vector<T> &v) : arr_size((char)v.size()), ind(0) {
        // arr = new T[arr_size];
        for (T &elt : v) {
            arr[ind++] = elt;
        }
    }
    SmallVector() : arr_size(0), ind(0) {}
    SmallVector(int _size) : arr_size(_size), ind(0) {
        // arr = new T[arr_size];
    }
    void push_back(T elt) {
        arr[ind++] = elt;
        arr_size = max(arr_size, ind);
    }
    bool operator==(const SmallVector<T> &rhs) {
        if (arr_size != rhs.arr_size)
            return false;
        bool equal = true;
        for (int i = 0; i < arr_size; i++) {
            equal = equal & (arr[i] == rhs.arr[i]);
        }
        return equal;
    }
    bool operator==(const vector<T> &rhs) {
        if (arr_size != rhs.size())
            return false;
        bool equal = true;
        for (int i = 0; i < arr_size; i++) {
            equal = equal & (arr[i] == rhs[i]);
        }
        return equal;
    }
    T &operator[](int ii) { return arr[ii]; }
    void clear() { arr_size = ind = 0; }
    char size() { return arr_size; }
    void SetSize(int _size) {
        arr_size = (char)_size;
        ind = 0;
    }
    class iterator {
      public:
        typedef iterator self_type;
        typedef T value_type;
        typedef T &reference;
        typedef T *pointer;
        typedef std::forward_iterator_tag iterator_category;
        typedef int difference_type;
        iterator(pointer ptr) : ptr_(ptr) {}
        self_type operator++() {
            self_type i = *this;
            ptr_++;
            return i;
        }
        self_type operator++(int junk) {
            ptr_++;
            return *this;
        }
        reference operator*() { return *ptr_; }
        pointer operator->() { return ptr_; }
        bool operator==(const self_type &rhs) { return ptr_ == rhs.ptr_; }
        bool operator!=(const self_type &rhs) { return ptr_ != rhs.ptr_; }

      private:
        pointer ptr_;
    };

    class const_iterator {
      public:
        typedef const_iterator self_type;
        typedef T value_type;
        typedef T &reference;
        typedef T *pointer;
        typedef int difference_type;
        typedef std::forward_iterator_tag iterator_category;
        const_iterator(pointer ptr) : ptr_(ptr) {}
        self_type operator++() {
            self_type i = *this;
            ptr_++;
            return i;
        }
        self_type operator++(int junk) {
            ptr_++;
            return *this;
        }
        const reference operator*() { return *ptr_; }
        const pointer operator->() { return ptr_; }
        bool operator==(const self_type &rhs) { return ptr_ == rhs.ptr_; }
        bool operator!=(const self_type &rhs) { return ptr_ != rhs.ptr_; }

      private:
        pointer ptr_;
    };
    iterator begin() { return iterator(arr); }
    iterator end() { return iterator(arr + arr_size); }
    const_iterator begin() const { return const_iterator(arr); }
    const_iterator end() const { return const_iterator(arr + arr_size); }
    friend ostream &operator<<(ostream &os, SmallVector<T> &sv) {
        os << "[";
        for (int i = 0; i < sv.size(); ++i) {
            os << sv[i];
            if (i != sv.size() - 1)
                os << ", ";
        }
        os << "]";
        return os;
    }
    iterator find(const T &val) {
        iterator first = begin(), last = end();
        while (first != last) {
            if (*first == val)
                return first;
            else
                ++first;
        }
        return first;
    }
};

typedef pair<int, int> PII;
typedef pair<double, double> PDD;
typedef SmallVector<int> Path;
typedef PII Link;
//! TODO: run speed tests b/w set and unordered_set
typedef set<int> Hypothesis; // contains link_ids

namespace std {
template <> struct hash<PII> {
    std::size_t operator()(const PII &pii) const {
        return hash<int>()(pii.first) ^ hash<int>()(pii.second);
    }
};
} // namespace std

struct HypothesisPointerCompare {
    explicit HypothesisPointerCompare(Hypothesis *h_) : h(h_) {}
    inline bool operator()(const Hypothesis *h2) const { return *h == *h2; }

  private:
    Hypothesis *h;
};

/*
template< class T1, class T2 >
constexpr bool operator==( const pair<T1,T2>& lhs, const pair<T1,T2>& rhs );
*/

// C++ template to print pair<>
template <typename T, typename S>
ostream &operator<<(ostream &os, const pair<T, S> &v) {
    os << "(";
    os << v.first << ", " << v.second << ")";
    return os;
}

// C++ template to print pair<>
// class by using template
template <typename T, typename S>
constexpr pair<T, S> operator+(const pair<T, S> &v1, const pair<T, S> &v2) {
    return pair<T, S>(v1.first + v2.first, v1.second + v2.second);
}

template <typename T> ostream &operator<<(ostream &os, const vector<T> &v) {
    os << "[";
    for (int i = 0; i < v.size(); ++i) {
        os << v[i];
        if (i != v.size() - 1)
            os << ", ";
    }
    os << "]";
    return os;
}

template <typename T> ostream &operator<<(ostream &os, const set<T> &v) {
    os << "[";
    for (auto it : v) {
        os << it;
        if (it != *v.rbegin())
            os << ", ";
    }
    os << "]";
    return os;
}

template <typename K, typename V>
ostream &operator<<(ostream &os, dense_hash_map<K, V, hash<K>> &v) {
    os << "[";
    auto it = v.begin();
    while (it != v.end()) {
        os << "(" << it->first << "," << it->second << ")";
        if (++it != v.end())
            os << ", ";
    }
    os << "]";
    return os;
}

// C++ template to print unordered_set container elements
template <typename T>
ostream &operator<<(ostream &os, const unordered_set<T> &v) {
    os << "[";
    bool first = true;
    for (auto it : v) {
        if (!first)
            os << ", ";
        os << it;
        first = false;
    }
    os << "]";
    return os;
}

class SpinLock {
    std::atomic_flag locked = ATOMIC_FLAG_INIT;

  public:
    void lock() {
        while (locked.test_and_set(std::memory_order_acquire))
            ;
    }
    void unlock() { locked.clear(std::memory_order_release); }
};

static inline double
GetTimeSinceSeconds(chrono::time_point<chrono::system_clock> start_time) {
    return chrono::duration_cast<chrono::milliseconds>(
               chrono::high_resolution_clock::now() - start_time)
               .count() *
           1.0e-3;
}

#endif

// PACE 2026 Heuristic track --- Rooted Maximum Agreement Forest (MAF) solver.
//
// Algorithm (anytime randomized-restart greedy):
//   * Construction: "merge-first" common-cherry contraction. Repeatedly
//     contract any cherry (a,b) that is a cherry in BOTH trees (an agreement,
//     which never increases forest size); when no common cherry remains but
//     the trees still disagree, cut one leaf of a conflicting T1-cherry (it
//     becomes its own component). This is the constructive skeleton of the
//     classic rooted-MAF 3-approximation (Bordewich-Semple / Whidden-Zeh).
//   * Search: restart the construction many times with randomized cherry
//     ordering / cut selection, keeping the minimum-size forest, until the
//     time budget (SIGTERM or internal clock) runs out.
//
// Correctness: components are built exclusively from agreements (common
// cherries) and singletons, so each component's induced restriction is equal
// in both trees and the components are disjoint -- exactly the agreement-forest
// feasibility the official checker enforces.
//
// I/O: instance on stdin (PACE 2026 format), forest on stdout, one Newick
// tree per line terminated with ';'. A SIGTERM handler always emits a valid
// best-so-far solution (all-singletons until the first greedy finishes, then
// the best forest found) so the process never dies without a feasible answer.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <csignal>
#include <ctime>
#include <unistd.h>
#include <vector>
#include <string>
#include <atomic>
#include <random>
#include <algorithm>
#include <climits>

using namespace std;

// ----------------------------- SIGTERM safety -----------------------------
// An immutable, fully-built solution buffer. The best one found so far is
// published via an atomic pointer; the (async-signal) handler loads it and
// writes it verbatim. Old buffers are intentionally leaked (few updates).
struct Sol { char* data; size_t len; };
static std::atomic<Sol*> g_cur{nullptr};

static void on_sigterm(int) {
    Sol* s = g_cur.load(std::memory_order_acquire);
    if (s && s->data) {
        ssize_t r = write(STDOUT_FILENO, s->data, s->len);
        (void)r;
    }
    _exit(0);
}

static double now_sec() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

// ----------------------------- Tree structure -----------------------------
// A rooted binary tree over "groups". A leaf carries a group id; the same id
// identifies the corresponding leaf in the other tree.
struct Tree {
    vector<int> par, c0, c1, grp;
    int root = -1;
    int nodes = 0;

    int alloc(int p) {
        int id = nodes++;
        par.push_back(p); c0.push_back(-1); c1.push_back(-1); grp.push_back(-1);
        return id;
    }
    inline bool is_leaf(int v) const { return c0[v] < 0; }
    inline void attach(int p, int v) { if (c0[p] < 0) c0[p] = v; else c1[p] = v; }
    inline int sibling(int v) const {
        int p = par[v];
        return (p < 0) ? -1 : (c0[p] == v ? c1[p] : c0[p]);
    }
    inline void replace_child(int p, int oldc, int newc) {
        if (c0[p] == oldc) c0[p] = newc; else c1[p] = newc;
    }
};

// Parse one Newick line into tree T, recording leaf node indices in leafpos.
static void parse_newick(const string& s, Tree& T, vector<int>& leafpos, int n) {
    T.par.reserve(2 * n + 4); T.c0.reserve(2 * n + 4);
    T.c1.reserve(2 * n + 4); T.grp.reserve(2 * n + 4);
    vector<int> stk;
    size_t i = 0, m = s.size();
    while (i < m) {
        char ch = s[i];
        if (ch == '(') {
            int v = T.alloc(stk.empty() ? -1 : stk.back());
            if (!stk.empty()) T.attach(stk.back(), v);
            if (T.root < 0) T.root = v;
            stk.push_back(v); ++i;
        } else if (ch == ')') {
            if (!stk.empty()) stk.pop_back();
            ++i;
        } else if (ch == ',' || ch == ' ' || ch == '\t' || ch == '\r' || ch == ';') {
            ++i;
        } else if (ch >= '0' && ch <= '9') {
            long lab = 0;
            while (i < m && s[i] >= '0' && s[i] <= '9') { lab = lab * 10 + (s[i] - '0'); ++i; }
            int v = T.alloc(stk.empty() ? -1 : stk.back());
            if (!stk.empty()) T.attach(stk.back(), v);
            if (T.root < 0) T.root = v;
            T.grp[v] = (int)lab;
            leafpos[lab] = v;
        } else { ++i; }
    }
}

// ---------------------- one randomized construction -----------------------
// Returns the forest size k; appends the serialized forest (one ';'-terminated
// Newick tree per line) into `out`. `randomize` toggles random ordering/cuts.
// O1/O2 are the original parsed trees (copied per call).
static int solve_once(const Tree& O1, const Tree& O2, int n,
                      const vector<int>& opos1, const vector<int>& opos2,
                      bool randomize, std::mt19937& rng, string& out) {
    Tree T1 = O1, T2 = O2;   // working copies

    // group tables: group g == original leaf label g initially
    vector<int> gLabel(n + 1, -1), gLeft(n + 1, -1), gRight(n + 1, -1);
    for (int l = 1; l <= n; ++l) gLabel[l] = l;
    auto new_merge_group = [&](int a, int b) {
        int g = (int)gLabel.size();
        gLabel.push_back(-1); gLeft.push_back(a); gRight.push_back(b);
        return g;
    };

    vector<int> leaf1(n + 1, -1), leaf2(n + 1, -1);
    vector<char> alive(n + 1, 0);
    for (int l = 1; l <= n; ++l) { leaf1[l] = opos1[l]; leaf2[l] = opos2[l]; alive[l] = 1; }

    auto common_in_T2 = [&](int gu, int gv) -> bool {
        int u = leaf2[gu], w = leaf2[gv];
        return T2.par[u] >= 0 && T2.par[u] == T2.par[w];
    };
    auto is_cherry1 = [&](int v) -> bool {
        return !T1.is_leaf(v) && T1.is_leaf(T1.c0[v]) && T1.is_leaf(T1.c1[v]);
    };
    auto valid_cherry = [&](int v) -> bool {
        if (v < 0 || v >= T1.nodes || !is_cherry1(v)) return false;
        return alive[T1.grp[T1.c0[v]]] && alive[T1.grp[T1.c1[v]]];
    };

    vector<int> components;
    int active = n;
    vector<int> work; work.reserve(T1.nodes);
    for (int v = 0; v < T1.nodes; ++v) if (!T1.is_leaf(v)) work.push_back(v);
    if (randomize) std::shuffle(work.begin(), work.end(), rng);

    auto do_merge = [&](int p1, int gu, int gv) {
        int gm = new_merge_group(gu, gv);
        int p2 = T2.par[leaf2[gu]];
        T1.c0[p1] = -1; T1.c1[p1] = -1; T1.grp[p1] = gm;
        T2.c0[p2] = -1; T2.c1[p2] = -1; T2.grp[p2] = gm;
        if (gm >= (int)leaf1.size()) {
            leaf1.resize(gm + 1, -1); leaf2.resize(gm + 1, -1); alive.resize(gm + 1, 0);
        }
        leaf1[gm] = p1; leaf2[gm] = p2; alive[gm] = 1;
        alive[gu] = 0; alive[gv] = 0;
        --active;
        if (T1.par[p1] >= 0) work.push_back(T1.par[p1]);
    };
    auto do_cut = [&](int g) {
        components.push_back(g);
        alive[g] = 0;
        { int v = leaf1[g], p = T1.par[v];
          if (p >= 0) { int s = (T1.c0[p] == v) ? T1.c1[p] : T1.c0[p];
                        int gp = T1.par[p]; T1.par[s] = gp;
                        if (gp < 0) T1.root = s; else T1.replace_child(gp, p, s);
                        if (gp >= 0) work.push_back(gp); } }
        { int v = leaf2[g], p = T2.par[v];
          if (p >= 0) { int s = (T2.c0[p] == v) ? T2.c1[p] : T2.c0[p];
                        int gp = T2.par[p]; T2.par[s] = gp;
                        if (gp < 0) T2.root = s; else T2.replace_child(gp, p, s); } }
        --active;
    };
    auto choose_cut = [&](int v) -> int {
        int gu = T1.grp[T1.c0[v]], gv = T1.grp[T1.c1[v]];
        if (randomize && (rng() & 3) == 0) return (rng() & 1) ? gu : gv;  // explore
        int su = T2.sibling(leaf2[gu]), sv = T2.sibling(leaf2[gv]);
        bool u_in_cherry = (su >= 0 && T2.is_leaf(su));
        bool v_in_cherry = (sv >= 0 && T2.is_leaf(sv));
        if (u_in_cherry && !v_in_cherry) return gv;
        if (v_in_cherry && !u_in_cherry) return gu;
        return gu;
    };

    vector<int> conflicts;
    while (active > 1) {
        while (!work.empty()) {
            int v = work.back(); work.pop_back();
            if (!valid_cherry(v)) continue;
            int gu = T1.grp[T1.c0[v]], gv = T1.grp[T1.c1[v]];
            if (common_in_T2(gu, gv)) do_merge(v, gu, gv);
        }
        if (active <= 1) break;

        // collect valid conflict cherries; pick one (random or first)
        conflicts.clear();
        for (int v = 0; v < T1.nodes; ++v)
            if (valid_cherry(v)) {
                int gu = T1.grp[T1.c0[v]], gv = T1.grp[T1.c1[v]];
                if (!common_in_T2(gu, gv)) conflicts.push_back(v);
            }
        if (conflicts.empty()) break;
        int found = randomize ? conflicts[rng() % conflicts.size()] : conflicts.front();

        do_cut(choose_cut(found));
        for (int v = 0; v < T1.nodes; ++v) if (valid_cherry(v)) work.push_back(v);
        if (randomize) std::shuffle(work.begin(), work.end(), rng);
    }
    for (int g = 1; g < (int)alive.size(); ++g) if (alive[g]) components.push_back(g);

    // serialize (iterative, no recursion / no quadratic string building)
    static thread_local vector<pair<int,int>> st;
    for (int g : components) {
        st.clear(); st.push_back({g, 0});
        while (!st.empty()) {
            int node = st.back().first, stage = st.back().second;
            if (gLabel[node] >= 0) { out += to_string(gLabel[node]); st.pop_back(); }
            else if (stage == 0) { out += '('; st.back().second = 1; st.push_back({gLeft[node], 0}); }
            else if (stage == 1) { out += ','; st.back().second = 2; st.push_back({gRight[node], 0}); }
            else { out += ')'; st.pop_back(); }
        }
        out += ";\n";
    }
    return (int)components.size();
}

static Sol* make_sol(const string& s) {
    Sol* p = (Sol*)malloc(sizeof(Sol));
    p->len = s.size();
    p->data = (char*)malloc(s.size() + 1);
    memcpy(p->data, s.data(), s.size());
    return p;
}

int main(int /*argc*/, char** /*argv*/) {
    double t_start = now_sec();

    // time budget: STRIDE_TIMEOUT if set (dev runs), else 300s (PACE soft limit)
    double budget = 300.0;
    if (const char* e = getenv("STRIDE_TIMEOUT")) { double v = atof(e); if (v > 0) budget = v; }
    budget -= 0.7;  // safety margin before SIGTERM / hard kill

    // ---- read all of stdin ----
    string input;
    { char buf[1 << 16]; size_t r;
      while ((r = fread(buf, 1, sizeof(buf), stdin)) > 0) input.append(buf, r); }

    // ---- locate header `#p t n` and the two tree lines ----
    int n = 0, t = 0;
    vector<string> trees;
    { size_t i = 0, m = input.size();
      while (i < m) {
          size_t j = i; while (j < m && input[j] != '\n') ++j;
          size_t a = i; while (a < j && (input[a]==' '||input[a]=='\t'||input[a]=='\r')) ++a;
          if (a < j) {
              if (input[a] == '#') {
                  if (j - a >= 2 && input[a+1] == 'p') sscanf(input.c_str()+a, "#p %d %d", &t, &n);
              } else trees.emplace_back(input.substr(a, j - a));
          }
          i = (j < m) ? j + 1 : j;
      } }
    if (n <= 0) return 0;

    // ---- always-valid all-singletons fallback, published immediately ----
    { string s; s.reserve((size_t)n * 4);
      for (int l = 1; l <= n; ++l) { s += to_string(l); s += ";\n"; }
      g_cur.store(make_sol(s), std::memory_order_release); }

    // ---- install SIGTERM/SIGINT handlers ----
    { struct sigaction sa; memset(&sa, 0, sizeof(sa));
      sa.sa_handler = on_sigterm;
      sigaction(SIGTERM, &sa, nullptr); sigaction(SIGINT, &sa, nullptr); }

    if ((int)trees.size() < 2) {           // malformed -> emit fallback
        Sol* s = g_cur.load();
        fwrite(s->data, 1, s->len, stdout);
        return 0;
    }

    // ---- build original trees once ----
    Tree O1, O2;
    vector<int> pos1(n + 1, -1), pos2(n + 1, -1);
    parse_newick(trees[0], O1, pos1, n);
    parse_newick(trees[1], O2, pos2, n);

    std::mt19937 rng(12345);
    int best_k = INT32_MAX;

    // restart 0: deterministic construction (baseline quality guarantee)
    // restarts 1..: randomized, keep the strictly-better forest
    for (long iter = 0; ; ++iter) {
        string out;
        out.reserve((size_t)n * 4);
        int k = solve_once(O1, O2, n, pos1, pos2, /*randomize=*/iter > 0, rng, out);
        if (k < best_k) {
            best_k = k;
            g_cur.store(make_sol(out), std::memory_order_release);
        }
        if (best_k <= 1) break;                       // optimal (identical trees)
        if (now_sec() - t_start > budget) break;      // out of time
    }

    // ---- print best-so-far and exit cleanly (ignore late SIGTERM) ----
    signal(SIGTERM, SIG_IGN); signal(SIGINT, SIG_IGN);
    Sol* s = g_cur.load(std::memory_order_acquire);
    fwrite(s->data, 1, s->len, stdout);
    fflush(stdout);
    return 0;
}

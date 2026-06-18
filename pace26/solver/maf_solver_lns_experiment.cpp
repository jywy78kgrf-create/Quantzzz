// ============================================================================
// UNUSED EXPERIMENT (kept for the record). Large-neighbourhood search
// (destroy-and-repair): dissolve a random subset of the forest's components,
// restrict both trees to those leaves, re-solve, and substitute back only if the
// reassembled forest is a valid agreement forest (checked in-process via
// binary-lifting LCA + Steiner-tree disjointness). RESULT: ineffective on the
// PACE instances — the gate rejects ~99.99% of improving substitutions because
// re-merged sub-blocks pervasively overlap the kept components (acceptance
// ~6 / 126000 moves). The shipped solver (maf_solver.cpp) — strong greedy +
// diversified restarts — is better and is what should be submitted.
// ============================================================================
//
// PACE 2026 Heuristic track --- Rooted Maximum Agreement Forest (MAF) solver.
//
// Two-stage anytime solver:
//   1. Construction: "merge-first" common-cherry contraction with a lookahead /
//      3-approximation cut rule (drive from either tree, randomized restarts).
//   2. Large-neighbourhood search (destroy-and-repair): dissolve a random subset
//      of the current forest's components, restrict BOTH trees to exactly those
//      leaves, and re-solve that subproblem. Re-solving in isolation removes the
//      global constraints that forced suboptimal cuts, so it can only help.
//
// Correctness of the LNS move (by construction, no checker needed): the
// components outside the dissolved set are still detachable pendant subtrees, so
// deleting their edges leaves exactly the restriction of each tree to the
// dissolved leaves; any valid agreement forest of that restricted instance can
// therefore be substituted back, yielding a valid agreement forest of the whole.
//
// I/O: instance on stdin (PACE 2026 format), forest on stdout (one ';'-terminated
// Newick tree per line). A SIGTERM handler always emits a valid best-so-far
// forest, so the process never dies without a feasible answer.

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
struct Sol { char* data; size_t len; };
static std::atomic<Sol*> g_cur{nullptr};

static void on_sigterm(int) {
    Sol* s = g_cur.load(std::memory_order_acquire);
    if (s && s->data) { ssize_t r = write(STDOUT_FILENO, s->data, s->len); (void)r; }
    _exit(0);
}
static double now_sec() {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

// ----------------------------- Tree structure -----------------------------
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
    void clear_all() { par.clear(); c0.clear(); c1.clear(); grp.clear(); nodes = 0; root = -1; }
};

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
        } else if (ch == ')') { if (!stk.empty()) stk.pop_back(); ++i; }
        else if (ch == ',' || ch == ' ' || ch == '\t' || ch == '\r' || ch == ';') ++i;
        else if (ch >= '0' && ch <= '9') {
            long lab = 0;
            while (i < m && s[i] >= '0' && s[i] <= '9') { lab = lab * 10 + (s[i] - '0'); ++i; }
            int v = T.alloc(stk.empty() ? -1 : stk.back());
            if (!stk.empty()) T.attach(stk.back(), v);
            if (T.root < 0) T.root = v;
            T.grp[v] = (int)lab; leafpos[lab] = v;
        } else ++i;
    }
}

// Build the induced restriction of `orig` to the kept leaves, relabelled by
// `origToLocal` (origlabel -> local label 1..m, or 0 if not kept). Produces a
// binary tree over local labels with degree-2 nodes suppressed. O(orig.nodes).
static void restrict_tree(const Tree& orig, const vector<int>& origToLocal,
                          int m, Tree& out, vector<int>& pos) {
    int N = orig.nodes;
    // preorder (parents before children), then process in reverse for post-order
    static thread_local vector<int> order, stk;
    order.clear(); stk.clear();
    stk.push_back(orig.root);
    while (!stk.empty()) {
        int v = stk.back(); stk.pop_back(); order.push_back(v);
        if (orig.c0[v] >= 0) stk.push_back(orig.c0[v]);
        if (orig.c1[v] >= 0) stk.push_back(orig.c1[v]);
    }
    static thread_local vector<int> cnt, rep;
    cnt.assign(N, 0); rep.assign(N, -1);
    for (int i = (int)order.size() - 1; i >= 0; --i) {
        int v = order[i];
        if (orig.is_leaf(v)) {
            int lab = orig.grp[v];
            cnt[v] = (lab > 0 && lab < (int)origToLocal.size() && origToLocal[lab] > 0) ? 1 : 0;
        } else cnt[v] = cnt[orig.c0[v]] + cnt[orig.c1[v]];
    }
    out.clear_all();
    out.par.reserve(2 * m + 2); out.c0.reserve(2 * m + 2);
    out.c1.reserve(2 * m + 2); out.grp.reserve(2 * m + 2);
    pos.assign(m + 1, -1);
    for (int i = (int)order.size() - 1; i >= 0; --i) {
        int v = order[i];
        if (cnt[v] == 0) continue;
        if (orig.is_leaf(v)) {
            int loc = origToLocal[orig.grp[v]];
            int w = out.alloc(-1); out.grp[w] = loc; pos[loc] = w; rep[v] = w;
        } else {
            int lc = cnt[orig.c0[v]] > 0 ? rep[orig.c0[v]] : -1;
            int rc = cnt[orig.c1[v]] > 0 ? rep[orig.c1[v]] : -1;
            if (lc >= 0 && rc >= 0) {
                int w = out.alloc(-1);
                out.c0[w] = lc; out.c1[w] = rc; out.par[lc] = w; out.par[rc] = w; rep[v] = w;
            } else rep[v] = (lc >= 0) ? lc : rc;
        }
    }
    out.root = (cnt[orig.root] > 0) ? rep[orig.root] : -1;
    if (out.root >= 0) out.par[out.root] = -1;
}

// A forest component: its leaf set (original labels) and its Newick string
// (original labels, no trailing ';').
struct Block { vector<int> leaves; string nwk; };

// Binary-lifting LCA over a tree (built once per input tree).
struct LCA {
    int LOG = 1;
    vector<int> depth;
    vector<vector<int>> jmp;
    void build(const Tree& T) {
        int N = T.nodes; depth.assign(N, 0);
        LOG = 1; while ((1 << LOG) < (N + 1)) ++LOG;
        jmp.assign(LOG, vector<int>(N, -1));
        vector<int> order; order.reserve(N);
        vector<int> stk; stk.push_back(T.root);
        while (!stk.empty()) { int v = stk.back(); stk.pop_back(); order.push_back(v);
            if (T.c0[v] >= 0) stk.push_back(T.c0[v]); if (T.c1[v] >= 0) stk.push_back(T.c1[v]); }
        for (int v : order) { jmp[0][v] = T.par[v]; depth[v] = (T.par[v] < 0) ? 0 : depth[T.par[v]] + 1; }
        for (int k = 1; k < LOG; ++k) for (int v = 0; v < N; ++v) {
            int m = jmp[k-1][v]; jmp[k][v] = (m < 0) ? -1 : jmp[k-1][m];
        }
    }
    int lca(int a, int b) const {
        if (depth[a] < depth[b]) std::swap(a, b);
        int d = depth[a] - depth[b];
        for (int k = 0; k < LOG; ++k) if ((d >> k) & 1) a = jmp[k][a];
        if (a == b) return a;
        for (int k = LOG - 1; k >= 0; --k) if (jmp[k][a] != jmp[k][b]) { a = jmp[k][a]; b = jmp[k][b]; }
        return jmp[0][a];
    }
};

// Verify the partition `blocks` is a valid agreement forest of tree T: the
// minimal spanning (Steiner) subtrees of the blocks must be pairwise node-
// disjoint. We mark, for each block, the path from each of its leaves up to the
// block's LCA; a node claimed by two blocks means their components overlap.
static bool valid_forest(const vector<Block>& blocks, const Tree& T,
                         const vector<int>& pos, const LCA& lca) {
    static thread_local vector<int> markBid;
    markBid.assign(T.nodes, -1);
    for (int bi = 0; bi < (int)blocks.size(); ++bi) {
        const auto& B = blocks[bi].leaves;
        if (B.empty()) continue;
        int L = pos[B[0]];
        for (size_t i = 1; i < B.size(); ++i) L = lca.lca(L, pos[B[i]]);
        for (int lab : B) {
            int v = pos[lab];
            while (true) {
                if (markBid[v] == bi) break;
                if (markBid[v] != -1) return false;
                markBid[v] = bi;
                if (v == L) break;
                v = T.par[v];
            }
        }
    }
    return true;
}

// ---------------------- one randomized construction -----------------------
// Greedy MAF on (O1,O2) over local labels 1..n; returns components as Blocks
// whose leaves/Newick use ORIGINAL labels via localToOrig. (Algorithm unchanged
// from the tuned single-tree solver: merge-first contraction + lookahead /
// 3-approximation cut + max-gain conflict selection + diversified restarts.)
static vector<Block> greedy_blocks(const Tree& O1, const Tree& O2, int n,
                                   const vector<int>& opos1, const vector<int>& opos2,
                                   const vector<int>& localToOrig,
                                   bool randomize, std::mt19937& rng) {
    Tree T1 = O1, T2 = O2;
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

    auto push_grp = [&](int g) {
        if (g < 0 || g >= (int)leaf1.size() || !alive[g]) return;
        int lf = leaf1[g]; if (lf < 0) return;
        int p = T1.par[lf]; if (p >= 0) work.push_back(p);
    };
    auto do_merge = [&](int p1, int gu, int gv) {
        int gm = new_merge_group(gu, gv);
        int p2 = T2.par[leaf2[gu]];
        T1.c0[p1] = -1; T1.c1[p1] = -1; T1.grp[p1] = gm;
        T2.c0[p2] = -1; T2.c1[p2] = -1; T2.grp[p2] = gm;
        if (gm >= (int)leaf1.size()) {
            leaf1.resize(gm + 1, -1); leaf2.resize(gm + 1, -1); alive.resize(gm + 1, 0);
        }
        leaf1[gm] = p1; leaf2[gm] = p2; alive[gm] = 1;
        alive[gu] = 0; alive[gv] = 0; --active;
        if (T1.par[p1] >= 0) work.push_back(T1.par[p1]);
    };
    auto do_cut = [&](int g) {
        components.push_back(g); alive[g] = 0;
        { int v = leaf1[g], p = T1.par[v];
          if (p >= 0) { int s = (T1.c0[p] == v) ? T1.c1[p] : T1.c0[p];
                        int gp = T1.par[p]; T1.par[s] = gp;
                        if (gp < 0) T1.root = s; else T1.replace_child(gp, p, s);
                        if (gp >= 0) work.push_back(gp); } }
        { int v = leaf2[g], p = T2.par[v];
          if (p >= 0) { int s = (T2.c0[p] == v) ? T2.c1[p] : T2.c0[p];
                        int gp = T2.par[p]; T2.par[s] = gp;
                        if (gp < 0) T2.root = s; else T2.replace_child(gp, p, s);
                        if (T2.is_leaf(s)) push_grp(T2.grp[s]);
                        if (gp >= 0) { int y = (T2.c0[gp] == s) ? T2.c1[gp] : T2.c0[gp];
                                       if (y >= 0 && T2.is_leaf(y)) push_grp(T2.grp[y]); } } }
        --active;
    };
    auto gain = [&](int gx) -> int {
        int g = 0;
        int l1 = leaf1[gx], p1 = T1.par[l1];
        if (p1 >= 0) {
            int s1 = (T1.c0[p1] == l1) ? T1.c1[p1] : T1.c0[p1];
            int gp1 = T1.par[p1];
            if (gp1 >= 0 && s1 >= 0 && T1.is_leaf(s1)) {
                int y1 = (T1.c0[gp1] == p1) ? T1.c1[gp1] : T1.c0[gp1];
                if (y1 >= 0 && T1.is_leaf(y1)) {
                    int a = T1.grp[s1], b = T1.grp[y1];
                    if (alive[a] && alive[b] && common_in_T2(a, b)) ++g;
                }
            }
        }
        int l2 = leaf2[gx], p2 = T2.par[l2];
        if (p2 >= 0) {
            int s2 = (T2.c0[p2] == l2) ? T2.c1[p2] : T2.c0[p2];
            int gp2 = T2.par[p2];
            if (gp2 >= 0 && s2 >= 0 && T2.is_leaf(s2)) {
                int y2 = (T2.c0[gp2] == p2) ? T2.c1[gp2] : T2.c0[gp2];
                if (y2 >= 0 && T2.is_leaf(y2)) {
                    int a = T2.grp[s2], b = T2.grp[y2];
                    if (alive[a] && alive[b]) {
                        int la = leaf1[a], lb = leaf1[b];
                        if (T1.par[la] >= 0 && T1.par[la] == T1.par[lb]) ++g;
                    }
                }
            }
        }
        return g;
    };
    auto best_cut = [&](int v, int& out_gain) -> int {
        int gu = T1.grp[T1.c0[v]], gv = T1.grp[T1.c1[v]];
        int cand[4]; int nc = 0;
        cand[nc++] = gu; cand[nc++] = gv;
        int su = T2.sibling(leaf2[gu]);
        if (su >= 0 && T2.is_leaf(su) && alive[T2.grp[su]]) cand[nc++] = T2.grp[su];
        int sv = T2.sibling(leaf2[gv]);
        if (sv >= 0 && T2.is_leaf(sv) && alive[T2.grp[sv]]) cand[nc++] = T2.grp[sv];
        auto harm = [&](int gx) { int s = T2.sibling(leaf2[gx]); return (s >= 0 && T2.is_leaf(s)) ? 1 : 0; };
        int best = cand[0], bg = gain(cand[0]), bh = harm(cand[0]), ties = 1;
        for (int i = 1; i < nc; ++i) {
            int gg = gain(cand[i]), h = harm(cand[i]);
            if (gg > bg || (gg == bg && h < bh)) { bg = gg; bh = h; best = cand[i]; ties = 1; }
            else if (gg == bg && h == bh) { ++ties; if (randomize && (rng() % ties) == 0) best = cand[i]; }
        }
        out_gain = bg; return best;
    };

    vector<int> conflictStack;
    while (active > 1) {
        while (!work.empty()) {
            int v = work.back(); work.pop_back();
            if (!valid_cherry(v)) continue;
            int gu = T1.grp[T1.c0[v]], gv = T1.grp[T1.c1[v]];
            if (common_in_T2(gu, gv)) do_merge(v, gu, gv);
        }
        if (active <= 1) break;
        conflictStack.clear();
        for (int v = 0; v < T1.nodes; ++v) {
            if (!valid_cherry(v)) continue;
            int gu = T1.grp[T1.c0[v]], gv = T1.grp[T1.c1[v]];
            if (common_in_T2(gu, gv)) work.push_back(v);
            else conflictStack.push_back(v);
        }
        if (!work.empty()) continue;
        if (conflictStack.empty()) break;
        int cut_leaf = -1, best_gain = -1, ties = 0;
        for (int v : conflictStack) {
            int g, leaf = best_cut(v, g);
            if (g > best_gain) { best_gain = g; cut_leaf = leaf; ties = 1; }
            else if (g == best_gain) { ++ties; if (randomize && (rng() % ties) == 0) cut_leaf = leaf; }
        }
        do_cut(cut_leaf);
    }
    for (int g = 1; g < (int)alive.size(); ++g) if (alive[g]) components.push_back(g);

    // extract each component as a Block (original-labelled leaves + Newick)
    vector<Block> blocks; blocks.reserve(components.size());
    vector<pair<int,int>> st;
    for (int g : components) {
        Block b;
        st.clear(); st.push_back({g, 0});
        while (!st.empty()) {
            int node = st.back().first, stage = st.back().second;
            if (gLabel[node] >= 0) {
                int o = localToOrig[gLabel[node]];
                b.nwk += to_string(o); b.leaves.push_back(o); st.pop_back();
            } else if (stage == 0) { b.nwk += '('; st.back().second = 1; st.push_back({gLeft[node], 0}); }
            else if (stage == 1) { b.nwk += ','; st.back().second = 2; st.push_back({gRight[node], 0}); }
            else { b.nwk += ')'; st.pop_back(); }
        }
        blocks.push_back(std::move(b));
    }
    return blocks;
}

static string solution_string(const vector<Block>& blocks) {
    size_t tot = 0; for (auto& b : blocks) tot += b.nwk.size() + 2;
    string s; s.reserve(tot);
    for (auto& b : blocks) { s += b.nwk; s += ";\n"; }
    return s;
}
static Sol* make_sol(const string& s) {
    Sol* p = (Sol*)malloc(sizeof(Sol));
    p->len = s.size(); p->data = (char*)malloc(s.size() + 1);
    memcpy(p->data, s.data(), s.size());
    return p;
}
static void publish(const vector<Block>& blocks) {
    g_cur.store(make_sol(solution_string(blocks)), std::memory_order_release);
}

int main(int, char**) {
    double t_start = now_sec();
    double budget = 300.0;
    if (const char* e = getenv("STRIDE_TIMEOUT")) { double v = atof(e); if (v > 0) budget = v; }
    budget -= 0.7;

    string input;
    { char buf[1 << 16]; size_t r;
      while ((r = fread(buf, 1, sizeof(buf), stdin)) > 0) input.append(buf, r); }

    int n = 0, t = 0;
    vector<string> trees;
    { size_t i = 0, m = input.size();
      while (i < m) {
          size_t j = i; while (j < m && input[j] != '\n') ++j;
          size_t a = i; while (a < j && (input[a]==' '||input[a]=='\t'||input[a]=='\r')) ++a;
          if (a < j) {
              if (input[a] == '#') { if (j - a >= 2 && input[a+1] == 'p') sscanf(input.c_str()+a, "#p %d %d", &t, &n); }
              else trees.emplace_back(input.substr(a, j - a));
          }
          i = (j < m) ? j + 1 : j;
      } }
    if (n <= 0) return 0;

    { string s; s.reserve((size_t)n * 4);
      for (int l = 1; l <= n; ++l) { s += to_string(l); s += ";\n"; }
      g_cur.store(make_sol(s), std::memory_order_release); }
    { struct sigaction sa; memset(&sa, 0, sizeof(sa));
      sa.sa_handler = on_sigterm; sigaction(SIGTERM, &sa, nullptr); sigaction(SIGINT, &sa, nullptr); }
    if ((int)trees.size() < 2) { Sol* s = g_cur.load(); fwrite(s->data, 1, s->len, stdout); return 0; }

    Tree O1, O2;
    vector<int> pos1(n + 1, -1), pos2(n + 1, -1);
    parse_newick(trees[0], O1, pos1, n);
    parse_newick(trees[1], O2, pos2, n);

    std::mt19937 rng(12345);
    vector<int> identity(n + 1); for (int i = 0; i <= n; ++i) identity[i] = i;
    LCA lca1, lca2; lca1.build(O1); lca2.build(O2);

    // debug: DEBUG_RESTRICT=K -> print T1|{1..K} and T2|{1..K} (original labels)
    if (const char* d = getenv("DEBUG_RESTRICT")) {
        int K = atoi(d);
        vector<int> o2l(n + 1, 0), l2o(1, 0);
        for (int lab = 1; lab <= K && lab <= n; ++lab) { o2l[lab] = (int)l2o.size(); l2o.push_back(lab); }
        int m = (int)l2o.size() - 1;
        auto dump = [&](const Tree& O) {
            Tree R; vector<int> rp; restrict_tree(O, o2l, m, R, rp);
            string out; vector<pair<int,int>> st; st.push_back({R.root, 0});
            while (!st.empty()) {
                int node = st.back().first, stage = st.back().second;
                if (R.is_leaf(node)) { out += to_string(l2o[R.grp[node]]); st.pop_back(); }
                else if (stage == 0) { out += '('; st.back().second = 1; st.push_back({R.c0[node], 0}); }
                else if (stage == 1) { out += ','; st.back().second = 2; st.push_back({R.c1[node], 0}); }
                else { out += ')'; st.pop_back(); }
            }
            printf("%s;\n", out.c_str());
        };
        dump(O1); dump(O2);
        return 0;
    }

    // ---- initial incumbent: deterministic both directions, keep the smaller ----
    vector<Block> best = greedy_blocks(O1, O2, n, pos1, pos2, identity, false, rng);
    { auto alt = greedy_blocks(O2, O1, n, pos2, pos1, identity, false, rng);
      if (alt.size() < best.size()) best.swap(alt); }
    publish(best);

    // ---- large-neighbourhood search: dissolve a subset, re-solve, accept if smaller ----
    // reusable scratch
    vector<int> origToLocal(n + 1, 0);
    Tree R1, R2; vector<int> rpos1, rpos2, localToOrig;
    vector<int> idx;
    long moves = 0, accepted = 0;
    while ((int)best.size() > 1 && now_sec() - t_start < budget) {
        int K = best.size();
        // choose a random set of blocks to dissolve, bounded total leaf count
        int capL = std::min(n, 400 + (int)(rng() % 600));   // target subproblem size
        idx.resize(K); for (int i = 0; i < K; ++i) idx[i] = i;
        // partial Fisher-Yates to grab a random prefix
        int chosen = 0, Lsize = 0;
        vector<int> pick;
        while (chosen < K) {
            int r = chosen + (int)(rng() % (K - chosen));
            std::swap(idx[chosen], idx[r]);
            pick.push_back(idx[chosen]);
            Lsize += (int)best[idx[chosen]].leaves.size();
            ++chosen;
            if (pick.size() >= 2 && Lsize >= capL) break;
        }
        if (pick.size() < 2) break;

        // build L label space
        localToOrig.assign(1, 0);   // index 0 unused
        for (int bi : pick) for (int o : best[bi].leaves) {
            origToLocal[o] = (int)localToOrig.size(); localToOrig.push_back(o);
        }
        int m = (int)localToOrig.size() - 1;

        // restrict both trees to L and re-solve (randomized)
        restrict_tree(O1, origToLocal, m, R1, rpos1);
        restrict_tree(O2, origToLocal, m, R2, rpos2);
        bool flip = (rng() & 1);
        vector<Block> sub = flip
            ? greedy_blocks(R2, R1, m, rpos2, rpos1, localToOrig, true, rng)
            : greedy_blocks(R1, R2, m, rpos1, rpos2, localToOrig, true, rng);

        if ((int)sub.size() < (int)pick.size()) {
            // candidate: replace dissolved blocks with the smaller sub-forest
            vector<char> drop(best.size(), 0);
            for (int bi : pick) drop[bi] = 1;
            vector<Block> nb; nb.reserve(best.size() - pick.size() + sub.size());
            for (int i = 0; i < (int)best.size(); ++i) if (!drop[i]) nb.push_back(best[i]);
            for (auto& b : sub) nb.push_back(b);
            // accept only if the reassembled forest is a valid agreement forest
            // of BOTH trees (sub-blocks can overlap outer blocks otherwise).
            if (valid_forest(nb, O1, pos1, lca1) && valid_forest(nb, O2, pos2, lca2)) {
                best.swap(nb);
                publish(best);
                ++accepted;
            }
        }
        for (int o : localToOrig) if (o > 0) origToLocal[o] = 0;   // reset scratch
        ++moves;
    }

    if (getenv("LNS_STATS"))
        fprintf(stderr, "moves=%ld accepted=%ld final_k=%d\n", moves, accepted, (int)best.size());

    signal(SIGTERM, SIG_IGN); signal(SIGINT, SIG_IGN);
    Sol* s = g_cur.load(std::memory_order_acquire);
    fwrite(s->data, 1, s->len, stdout); fflush(stdout);
    return 0;
}
